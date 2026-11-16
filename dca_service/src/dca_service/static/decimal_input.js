/*
 * Numbers typed into decimal fields: BTC amounts, prices, fees, multipliers.
 *
 * The fields are <input type="text" inputmode="decimal">, not type="number".
 * An iPhone set to a German region has only a comma on its decimal keypad, and
 * WebKit's number inputs drop that comma unless the phone's language is German,
 * so "0,5" arrived as 5. Here a comma and a point both mark the decimals.
 *
 * A form without novalidate had the browser check a number input's min and
 * max. Those attributes stay on the text fields, and the form's submit handler
 * asks reportProblem, which checks them the same way. A step was the
 * spinner's increment; a typed value needs none, so it is not checked.
 *
 * Classic script: in the browser it defines window.DecimalInput; under tests it
 * exports the same helpers through a CommonJS-style module object.
 */
(function (root, factory) {
    var api = factory();
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    } else {
        root.DecimalInput = api;
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    // Digits with at most one decimal mark, a comma or a point: "0,5", "0.5",
    // ",5", "5,". The exponent is what JavaScript writes when the page fills in
    // a tiny number (1e-8). Grouping such as 1.234,56 is not guessed at: it is
    // not read at all, so no amount is taken wrong in silence.
    var DECIMAL = /^-?(\d+([.,]\d*)?|[.,]\d+)(e-?\d+)?$/i;

    // The number in a decimal field's text, or NaN when it is empty or unreadable.
    function parse(text) {
        var s = String(text === null || text === undefined ? "" : text).trim();
        return DECIMAL.test(s) ? Number(s.replace(",", ".")) : NaN;
    }

    function given(attribute) {
        return attribute !== null && attribute !== undefined && attribute !== "";
    }

    // What is wrong with a field's text for its min and max attributes, in the
    // words of a number input; "" when nothing is. An empty field is left to
    // the required attribute.
    function problem(text, min, max) {
        if (String(text === null || text === undefined ? "" : text).trim() === "") return "";
        var value = parse(text);
        if (isNaN(value)) return "Enter a number, for example 0,5 or 0.5.";
        if (given(min) && value < Number(min)) return "Enter " + min + " or more.";
        if (given(max) && value > Number(max)) return "Enter " + max + " or less.";
        return "";
    }

    // Shows the first problem in a form's decimal fields at the field, as the
    // browser did for number inputs, and says whether there was one.
    function reportProblem(form) {
        // The form's elements, as the browser's own check takes them: a field
        // can belong to a form without sitting inside its tags
        var fields = form.elements;
        for (var i = 0; i < fields.length; i++) {
            var field = fields[i];
            if (field.tagName !== "INPUT" || field.getAttribute("inputmode") !== "decimal") continue;
            // The browser does not check these either
            if (field.disabled || field.readOnly) continue;
            var message = problem(field.value, field.getAttribute("min"), field.getAttribute("max"));
            if (!message) continue;
            field.setCustomValidity(message);
            // Cleared on the next edit, or the browser keeps refusing the form
            field.addEventListener("input", function clear(event) {
                event.target.setCustomValidity("");
            }, { once: true });
            field.reportValidity();
            return true;
        }
        return false;
    }

    return {
        parse: parse,
        problem: problem,
        reportProblem: reportProblem,
    };
});
