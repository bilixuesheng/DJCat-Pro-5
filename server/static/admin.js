(() => {
    const sidebar = document.querySelector("[data-sidebar]");
    const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
    const sidebarCloses = document.querySelectorAll("[data-sidebar-close]");

    if (sidebar && sidebarToggle && sidebarCloses.length) {
        const setSidebarOpen = (open) => {
            document.body.classList.toggle("sidebar-open", open);
            sidebarToggle.setAttribute("aria-expanded", String(open));
            sidebarToggle.setAttribute("aria-label", open ? "关闭导航" : "打开导航");
        };

        sidebarToggle.addEventListener("click", () => {
            setSidebarOpen(sidebarToggle.getAttribute("aria-expanded") !== "true");
        });
        sidebarCloses.forEach((closeButton) => {
            closeButton.addEventListener("click", () => setSidebarOpen(false));
        });
        sidebar.querySelectorAll("a").forEach((link) => {
            link.addEventListener("click", () => setSidebarOpen(false));
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && sidebarToggle.getAttribute("aria-expanded") === "true") {
                setSidebarOpen(false);
                sidebarToggle.focus();
            }
        });
        window.addEventListener("resize", () => {
            if (window.innerWidth > 900) setSidebarOpen(false);
        });
    }

    const dismiss = (toast) => {
        toast.classList.add("is-leaving");
        window.setTimeout(() => toast.remove(), 180);
    };

    document.querySelectorAll("[data-toast]").forEach((toast) => {
        toast.querySelector("[data-toast-close]")?.addEventListener("click", () => dismiss(toast));
        window.setTimeout(() => dismiss(toast), 5000);
    });

    let activeConfirm = null;
    const showConfirm = (form) => {
        if (activeConfirm) return;
        const previousFocus = document.activeElement;
        const backdrop = document.createElement("div");
        const dialog = document.createElement("section");
        const title = document.createElement("h2");
        const message = document.createElement("p");
        const actions = document.createElement("div");
        const cancelButton = document.createElement("button");
        const confirmButton = document.createElement("button");

        backdrop.className = "confirm-backdrop";
        dialog.className = "confirm-dialog";
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-labelledby", "confirm-title");
        title.id = "confirm-title";
        title.textContent = "确认操作";
        message.textContent = form.dataset.confirm;
        actions.className = "confirm-actions";
        cancelButton.className = "button button-secondary";
        cancelButton.type = "button";
        cancelButton.textContent = "取消";
        confirmButton.className = "button button-danger";
        confirmButton.type = "button";
        confirmButton.textContent = "确认重置";
        actions.append(cancelButton, confirmButton);
        dialog.append(title, message, actions);
        backdrop.append(dialog);
        document.body.append(backdrop);
        activeConfirm = backdrop;

        const close = () => {
            backdrop.remove();
            activeConfirm = null;
            previousFocus?.focus();
            document.removeEventListener("keydown", onKeyDown);
        };
        const onKeyDown = (event) => {
            if (event.key === "Escape") close();
        };
        cancelButton.addEventListener("click", close);
        confirmButton.addEventListener("click", () => {
            form.dataset.confirmed = "true";
            close();
            HTMLFormElement.prototype.submit.call(form);
        });
        backdrop.addEventListener("click", (event) => {
            if (event.target === backdrop) close();
        });
        document.addEventListener("keydown", onKeyDown);
        cancelButton.focus();
    };

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (form.dataset.confirmed === "true") {
                delete form.dataset.confirmed;
                return;
            }
            event.preventDefault();
            showConfirm(form);
        });
    });
})();
