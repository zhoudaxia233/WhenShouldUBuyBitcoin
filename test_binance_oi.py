import requests


def test_endpoint(url, params):
    print(f"Testing {url} with {params}...")
    try:
        response = requests.get(url, params=params, timeout=10)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Success! Got {len(data)} records.")
            print("Sample:", data[0] if data else "Empty")
        else:
            print("Response:", response.text)
    except Exception as e:
        print(f"Error: {e}")
    print("-" * 50)


# Test 1: fapi/v1/openInterestHist (The one that failed)
test_endpoint(
    "https://fapi.binance.com/fapi/v1/openInterestHist",
    {"symbol": "BTCUSDC", "period": "1d", "limit": 10},
)

# Test 2: futures/data/openInterestHist (Alternative)
test_endpoint(
    "https://fapi.binance.com/futures/data/openInterestHist",
    {"symbol": "BTCUSDC", "period": "1d", "limit": 10},
)

# Test 3: fapi/v1/openInterest (Current OI only)
test_endpoint("https://fapi.binance.com/fapi/v1/openInterest", {"symbol": "BTCUSDC"})
