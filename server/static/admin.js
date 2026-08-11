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
})();
