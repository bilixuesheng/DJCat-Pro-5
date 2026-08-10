const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

document.addEventListener("click", event => {
    const addButton = event.target.closest("[data-add-component]");
    if (addButton) {
        const list = document.querySelector("[data-component-list]");
        const template = document.querySelector("[data-component-template]");
        const draft = template.content.firstElementChild.cloneNode(true);
        list.appendChild(draft);
        if (!reducedMotion) {
            draft.animate(
                [
                    { opacity: 0, transform: "translateY(8px)" },
                    { opacity: 1, transform: "translateY(0)" },
                ],
                { duration: 280, easing: "cubic-bezier(.22, 1, .36, 1)" },
            );
        }
        draft.querySelector("input").focus();
        return;
    }

    const removeButton = event.target.closest("[data-remove-component]");
    if (!removeButton) return;
    const draft = removeButton.closest("[data-component-draft]");
    if (reducedMotion) {
        draft.remove();
        return;
    }
    const animation = draft.animate(
        [
            { opacity: 1, transform: "translateY(0)" },
            { opacity: 0, transform: "translateY(-6px)" },
        ],
        { duration: 180, easing: "ease-in" },
    );
    animation.finished.then(() => draft.remove());
});
