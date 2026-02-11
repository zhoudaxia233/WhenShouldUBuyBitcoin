"""
Tests for Static File Generator Service

Tests the static file generation service that triggers main.py to update
charts and data after DCA transactions.
"""
import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import subprocess

from dca_service.services.static_generator import (
    trigger_static_generation,
    check_static_generation_status
)


class TestStaticGeneratorBasic:
    """Basic tests for static file generator"""
    
    @patch('subprocess.Popen')
    @patch('sys.executable', '/usr/bin/python3')
    def test_trigger_background_success(self, mock_popen):
        """Test triggering static generation in background mode"""
        # Mock the subprocess
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process
        
        # Trigger generation
        result = trigger_static_generation(background=True)
        
        # Verify subprocess was called correctly
        assert result == mock_process
        assert mock_popen.called
        
        # Check that main.py path was used
        call_args = mock_popen.call_args
        command = call_args[0][0]
        assert command[0] == '/usr/bin/python3'
        assert str(command[1]).endswith('main.py')
        
        # Check that background options were set
        kwargs = call_args[1]
        assert kwargs['stderr'] == subprocess.STDOUT
        assert hasattr(kwargs['stdout'], 'name')
        assert str(kwargs['stdout'].name).endswith('data/static_generation.log')
        assert kwargs['text'] is True
    
    @patch('subprocess.run')
    @patch('sys.executable', '/usr/bin/python3')
    def test_trigger_synchronous_success(self, mock_run):
        """Test triggering static generation in synchronous mode"""
        # Mock the subprocess
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Analysis complete"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        # Trigger generation (synchronous)
        result = trigger_static_generation(background=False)
        
        # Verify subprocess was called
        assert result is None  # Synchronous returns None
        assert mock_run.called
        
        # Check command
        call_args = mock_run.call_args
        command = call_args[0][0]
        assert command[0] == '/usr/bin/python3'
        assert str(command[1]).endswith('main.py')
        
        # Check options
        kwargs = call_args[1]
        assert kwargs['capture_output'] is True
        assert kwargs['text'] is True
        assert kwargs['check'] is True
        assert kwargs['timeout'] == 300


class TestStaticGeneratorErrorHandling:
    """Tests for error handling in static generator"""
    
    @patch('pathlib.Path.exists', return_value=False)
    def test_main_py_not_found(self, mock_exists):
        """Test error when main.py doesn't exist"""
        with pytest.raises(FileNotFoundError) as exc_info:
            trigger_static_generation(background=True)
        
        assert "main.py not found" in str(exc_info.value)
    
    @patch('subprocess.run')
    @patch('sys.executable', '/usr/bin/python3')
    def test_synchronous_subprocess_error(self, mock_run):
        """Test handling of subprocess errors in synchronous mode"""
        # Mock subprocess failure
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=['python', 'main.py'],
            stderr="Error occurred"
        )
        
        # Should raise the error
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            trigger_static_generation(background=False)
        
        assert exc_info.value.returncode == 1
    
    @patch('subprocess.run')
    @patch('sys.executable', '/usr/bin/python3')
    def test_synchronous_timeout(self, mock_run):
        """Test handling of timeout in synchronous mode"""
        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=['python', 'main.py'],
            timeout=300
        )
        
        # Should raise the error
        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            trigger_static_generation(background=False)
        
        assert exc_info.value.timeout == 300


class TestProcessStatusCheck:
    """Tests for checking background process status"""
    
    def test_check_running_process(self):
        """Test checking status of a running process"""
        # Mock a running process
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Still running
        
        status = check_static_generation_status(mock_process)
        
        assert status['running'] is True
        assert status['exit_code'] is None
        assert status['stdout'] == ""
        assert status['stderr'] == ""
    
    def test_check_completed_process_success(self):
        """Test checking status of successfully completed process"""
        # Mock a completed process
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Exit code 0 (success)
        mock_process.communicate.return_value = ("Output data", "")
        
        status = check_static_generation_status(mock_process)
        
        assert status['running'] is False
        assert status['exit_code'] == 0
        assert status['stdout'] == "Output data"
        assert status['stderr'] == ""
    
    def test_check_completed_process_failure(self):
        """Test checking status of failed process"""
        # Mock a failed process
        mock_process = MagicMock()
        mock_process.poll.return_value = 1  # Exit code 1 (failure)
        mock_process.communicate.return_value = ("", "Error message")
        
        status = check_static_generation_status(mock_process)
        
        assert status['running'] is False
        assert status['exit_code'] == 1
        assert status['stdout'] == ""
        assert status['stderr'] == "Error message"


class TestPathResolution:
    """Tests for main.py path resolution"""
    
    @patch('subprocess.Popen')
    @patch('sys.executable', '/usr/bin/python3')
    def test_correct_path_resolution(self, mock_popen):
        """Test that main.py path is resolved correctly"""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process
        
        trigger_static_generation(background=True)
        
        # Get the command that was called
        call_args = mock_popen.call_args
        command = call_args[0][0]
        main_py_path = Path(command[1])
        
        # Verify the path structure
        # Should be: <project_root>/main.py
        assert main_py_path.name == "main.py"
        assert main_py_path.exists()  # Should exist in actual project
    
    @patch('subprocess.Popen')
    @patch('sys.executable', '/usr/bin/python3')
    def test_working_directory_set_correctly(self, mock_popen):
        """Test that working directory is set to project root"""
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process
        
        trigger_static_generation(background=True)
        
        # Check working directory
        call_args = mock_popen.call_args
        kwargs = call_args[1]
        cwd = Path(kwargs['cwd'])
        
        # CWD should contain main.py
        assert (cwd / 'main.py').exists()
