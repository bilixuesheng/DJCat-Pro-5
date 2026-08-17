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

    const dashboard = document.querySelector("[data-dashboard-stats-url]");
    if (dashboard) {
        let refreshing = false;
        let refreshStarted = false;
        let refreshTimer = null;
        const refreshStats = async () => {
            if (document.hidden || refreshing) return;
            refreshing = true;
            try {
                const response = await fetch(dashboard.dataset.dashboardStatsUrl, {
                    cache: "no-store",
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                });
                if (!response.ok) return;
                const stats = await response.json();
                document.querySelectorAll("[data-stat]").forEach((element) => {
                    const value = element.dataset.stat
                        .split(".")
                        .reduce((current, key) => current?.[key], stats);
                    if (value !== undefined && value !== null) element.textContent = value;
                });
            } catch (_) {
                // 后台统计失败不应打断正在进行的管理操作。
            } finally {
                refreshing = false;
            }
        };
        const syncStatsRefresh = () => {
            if (refreshTimer !== null) window.clearInterval(refreshTimer);
            refreshTimer = null;
            if (document.hidden) {
                refreshStarted = true;
                return;
            }
            if (refreshStarted) refreshStats();
            refreshStarted = true;
            refreshTimer = window.setInterval(refreshStats, 10_000);
        };
        document.addEventListener("visibilitychange", syncStatsRefresh);
        syncStatsRefresh();
    }

    const syncActionFields = (form) => {
        const type = form.querySelector("[data-action-type]");
        const argumentsWrapper = form.querySelector("[data-action-arguments-wrapper]");
        const target = form.querySelector("[data-action-target]");
        const help = form.querySelector("[data-action-help]");
        if (!type) return;
        const isProgram = type.value === "program";
        if (argumentsWrapper) argumentsWrapper.hidden = !isProgram;
        if (target) {
            target.placeholder = type.value === "url"
                ? "https://example.com"
                : type.value === "uri"
                    ? "例如：classisland://app/settings/general/"
                    : "例如：classisland.exe 或 bin/classisland.exe";
        }
        if (help) {
            help.textContent = type.value === "url"
                ? "网页目标必须使用 HTTPS。"
                : type.value === "uri"
                    ? "系统协议例如 classisland://app/settings/general/；危险协议会被拒绝。"
                    : "程序目标只能是安装目录内的相对 EXE；每行填写一个启动参数。";
        }
    };

    document.querySelectorAll("[data-action-form]").forEach((form) => {
        form.querySelector("[data-action-type]")?.addEventListener("change", () => syncActionFields(form));
        syncActionFields(form);
    });

    const dismissToast = (toast) => {
        if (toast.classList.contains("is-leaving")) return;
        toast.classList.add("is-leaving");
        window.setTimeout(() => toast.remove(), 280);
    };

    const prepareToast = (toast) => {
        if (toast.dataset.toastReady === "true") return;
        toast.dataset.toastReady = "true";
        let remaining = 10_000;
        let startedAt = Date.now();
        let timer = window.setTimeout(() => dismissToast(toast), 10_000);
        const pause = () => {
            if (timer !== null) {
                window.clearTimeout(timer);
                timer = null;
                remaining = Math.max(0, remaining - (Date.now() - startedAt));
            }
            toast.classList.add("is-paused");
        };
        const resume = () => {
            if (timer !== null || toast.classList.contains("is-leaving")) return;
            toast.classList.remove("is-paused");
            startedAt = Date.now();
            timer = window.setTimeout(() => dismissToast(toast), remaining);
        };
        toast.addEventListener("mouseenter", pause);
        toast.addEventListener("mouseleave", resume);
        toast.querySelector("[data-toast-close]")?.addEventListener("click", () => {
            dismissToast(toast);
        });
    };

    const toastRegion = () => {
        let region = document.querySelector(".toast-region");
        if (!region) {
            region = document.createElement("div");
            region.className = "toast-region";
            region.setAttribute("aria-live", "polite");
            region.setAttribute("aria-atomic", "true");
            document.body.append(region);
        }
        return region;
    };

    const showToast = (message, category = "info") => {
        if (!message) return;
        const toast = document.createElement("div");
        const mark = document.createElement("span");
        const text = document.createElement("p");
        const close = document.createElement("button");
        const progress = document.createElement("span");
        const toastCategory = category === "success" || category === "error" ? category : "info";

        toast.className = `toast toast-${toastCategory}`;
        toast.dataset.toast = "true";
        toast.setAttribute("role", toastCategory === "error" ? "alert" : "status");
        mark.className = "toast-mark";
        mark.setAttribute("aria-hidden", "true");
        text.textContent = message;
        close.className = "toast-close";
        close.type = "button";
        close.dataset.toastClose = "true";
        close.setAttribute("aria-label", "关闭提示");
        close.textContent = "×";
        progress.className = "toast-progress";
        progress.dataset.toastProgress = "true";
        progress.setAttribute("aria-hidden", "true");
        toast.append(mark, text, close, progress);
        toastRegion().append(toast);
        prepareToast(toast);
    };

    document.querySelectorAll("[data-toast]").forEach(prepareToast);

    const setButtonLoading = (form, loading) => {
        const button = form.querySelector("button[type=submit]");
        if (!button) return;
        if (loading) {
            button.dataset.originalLabel = button.textContent.trim();
            button.disabled = true;
            button.setAttribute("aria-busy", "true");
            button.classList.add("is-loading");
            const spinner = document.createElement("span");
            spinner.className = "button-spinner";
            spinner.setAttribute("aria-hidden", "true");
            button.replaceChildren(
                spinner,
                document.createTextNode("处理中…"),
            );
            return;
        }
        button.replaceChildren(document.createTextNode(button.dataset.originalLabel || "提交"));
        delete button.dataset.originalLabel;
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.classList.remove("is-loading");
    };

    const updateQuotaLabels = (form) => {
        const table = form.closest(".machine-section")?.querySelector("table[data-daily-limit]");
        if (!table) return;
        const limit = table.dataset.dailyLimit;
        const labels = form.dataset.resetKind === "all"
            ? table.querySelectorAll("[data-quota-label]")
            : form.closest("tr")?.querySelectorAll("[data-quota-label]");
        labels?.forEach((label) => {
            label.textContent = `${limit} / ${limit}`;
            const meter = label.previousElementSibling;
            if (meter?.tagName === "METER") meter.value = limit;
        });
    };

    const refreshTableOrder = (table) => {
        const controls = [...(table?.querySelectorAll("tbody .order-controls") || [])];
        controls.forEach((control, index) => {
            const position = control.querySelector(":scope > span");
            const up = control.querySelector('button[value="up"]');
            const down = control.querySelector('button[value="down"]');
            if (position) position.textContent = String(index + 1).padStart(2, "0");
            if (up) up.disabled = index === 0;
            if (down) down.disabled = index === controls.length - 1;
        });
    };

    const submitAsync = async (form) => {
        if (form.dataset.submitting === "true") return;
        form.dataset.submitting = "true";
        setButtonLoading(form, true);
        try {
            const response = await fetch(form.action, {
                method: (form.method || "POST").toUpperCase(),
                body: new FormData(form),
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            let payload = null;
            try {
                payload = await response.json();
            } catch (_) {
                payload = null;
            }
            if (!response.ok || !payload) {
                throw new Error(payload?.message || "操作失败，请稍后重试");
            }
            if (form.dataset.resetKind) updateQuotaLabels(form);
            showToast(payload?.message || "操作已完成", payload?.category || "success");
            if (form.dataset.removeOnSuccess) {
                const target = form.closest(form.dataset.removeOnSuccess);
                const table = target?.closest("table");
                target?.remove();
                refreshTableOrder(table);
                if (table?.dataset.emptyMessage && !table.tBodies[0]?.rows.length) {
                    const row = table.tBodies[0].insertRow();
                    const cell = row.insertCell();
                    cell.className = "empty";
                    cell.colSpan = table.tHead?.rows[0]?.cells.length || 1;
                    cell.textContent = table.dataset.emptyMessage;
                }
                const count = document.querySelector("[data-item-count]");
                if (target && count) {
                    count.textContent = String(Math.max(0, Number(count.textContent) - 1));
                }
            }
        } catch (error) {
            showToast(error.message || "操作失败，请稍后重试", "error");
        } finally {
            delete form.dataset.submitting;
            setButtonLoading(form, false);
        }
    };

    let activeConfirm = null;
    const showConfirm = (form, submitter = null) => {
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
        confirmButton.textContent = submitter?.textContent?.trim() || "确认";
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
            form.requestSubmit(submitter || undefined);
        });
        backdrop.addEventListener("click", (event) => {
            if (event.target === backdrop) close();
        });
        document.addEventListener("keydown", onKeyDown);
        cancelButton.focus();
    };

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (form.dataset.confirmed === "true") return;
            event.preventDefault();
            showConfirm(form);
        });
    });

    document.querySelectorAll("button[data-confirm]").forEach((button) => {
        const form = button.form;
        if (!form) return;
        button.addEventListener("click", (event) => {
            event.preventDefault();
            showConfirm(form, button);
        });
    });

    document.querySelectorAll("form[data-async-form]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (form.dataset.confirm && form.dataset.confirmed !== "true") return;
            if (form.dataset.confirmed === "true") delete form.dataset.confirmed;
            event.preventDefault();
            submitAsync(form);
        });
    });
})();
