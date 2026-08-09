(function () {
    "use strict";

    // --- Dark mode toggle -------------------------------------------------
    var themeToggle = document.getElementById("theme-toggle");
    function currentTheme() {
        var stored = localStorage.getItem("theme");
        if (stored === "dark" || stored === "light") return stored;
        return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    if (themeToggle) {
        themeToggle.addEventListener("click", function () {
            var next = currentTheme() === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", next);
            localStorage.setItem("theme", next);
        });
    }

    // --- Keyboard shortcuts -------------------------------------------------
    document.addEventListener("keydown", function (event) {
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        var target = event.target;
        var typing =
            target &&
            (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);

        if (event.key === "/" && !typing) {
            var search = document.getElementById("search-input");
            if (search) {
                event.preventDefault();
                search.focus();
                search.select();
            }
        } else if (event.key === "n" && !typing) {
            var company = document.getElementById("new-company");
            if (company) {
                event.preventDefault();
                company.focus();
            }
        }
    });

    // --- Required-field trim validation (belt-and-suspenders on top of server checks) --
    document.querySelectorAll("form[data-validate-required]").forEach(function (form) {
        form.addEventListener("submit", function (event) {
            var invalid = null;
            ["company", "role"].forEach(function (name) {
                var field = form.querySelector('[name="' + name + '"]');
                if (!field) return;
                field.value = field.value.trim();
                if (!field.value && !invalid) invalid = field;
            });
            if (invalid) {
                event.preventDefault();
                invalid.setCustomValidity("This field can't be blank or just spaces.");
                invalid.reportValidity();
                invalid.focus();
            } else {
                var company = form.querySelector('[name="company"]');
                var role = form.querySelector('[name="role"]');
                if (company) company.setCustomValidity("");
                if (role) role.setCustomValidity("");
            }
        });
    });

    // --- Undo-delete flash: auto-dismiss after a short window --------------
    document.querySelectorAll(".flash-undo").forEach(function (flash) {
        var bar = document.createElement("div");
        bar.className = "flash-undo-bar";
        flash.appendChild(bar);
        window.setTimeout(function () {
            flash.classList.add("flash-dismissed");
        }, 8000);
    });
})();
