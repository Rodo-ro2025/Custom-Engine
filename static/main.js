document.addEventListener("DOMContentLoaded", function() {
    const pageMode = document.body.dataset.pageMode;
    const documentTitle = document.body.dataset.documentTitle;
    const mainPage = document.body.dataset.mainPage;
    const editForm = document.getElementById("document-edit-form");
    const editTextarea = editForm ? editForm.querySelector('textarea[name="content"]') : null;
    let allowEditNavigation = false;

    document.querySelectorAll(".wiki-version-copy").forEach(function(copyButton) {
        copyButton.addEventListener("click", async function() {
            const source = document.getElementById(copyButton.getAttribute("data-copy-target"));
            if (!source) {
                return;
            }

            try {
                await navigator.clipboard.writeText(source.value);
            } catch (error) {
                source.focus();
                source.select();
                document.execCommand("copy");
                source.setSelectionRange(0, 0);
            }

            const originalText = copyButton.textContent;
            copyButton.textContent = "복사 완료";
            window.setTimeout(function() {
                copyButton.textContent = originalText;
            }, 1500);
        });
    });

    document.querySelectorAll(".wiki-footnote-reference").forEach(function(reference) {
        const link = reference.querySelector("a");
        const tooltip = reference.querySelector(".wiki-footnote-tooltip");
        let hideTimer = null;

        if (!link || !tooltip) {
            return;
        }

        const showTooltip = function() {
            window.clearTimeout(hideTimer);
            reference.classList.add("is-visible");
        };

        const hideTooltip = function() {
            hideTimer = window.setTimeout(function() {
                reference.classList.remove("is-visible");
            }, 100);
        };

        link.addEventListener("mouseenter", showTooltip);
        link.addEventListener("focus", showTooltip);
        link.addEventListener("mouseleave", hideTooltip);
        link.addEventListener("blur", hideTooltip);
        tooltip.addEventListener("mouseenter", function() {
            if (reference.classList.contains("is-visible")) {
                window.clearTimeout(hideTimer);
            }
        });
        tooltip.addEventListener("mouseleave", hideTooltip);
    });

    if (editTextarea) {
        const originalContent = editTextarea.value;

        window.addEventListener("beforeunload", function(event) {
            if (!allowEditNavigation && editTextarea.value !== originalContent) {
                event.preventDefault();
                event.returnValue = "편집한 내용이 저장되지 않았습니다. 정말로 나가시겠습니까?";
            }
        });

        editForm.addEventListener("submit", function() {
            allowEditNavigation = true;
        });

        document.addEventListener("click", function(event) {
            const link = event.target.closest("a[href]");
            if (!link || allowEditNavigation || editTextarea.value === originalContent) {
                return;
            }

            const destination = link.href;
            if (!window.confirm("편집한 내용이 저장되지 않았습니다. 정말로 나가시겠습니까?")) {
                event.preventDefault();
                return;
            }
            allowEditNavigation = true;
        });
    }

    document.addEventListener("keydown", function(event) {
        if (event.ctrlKey || event.altKey || event.metaKey) {
            return;
        }

        if (pageMode === "edit" || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
            return;
        }

        const shortcuts = {
            w: `/w/${encodeURIComponent(documentTitle)}`,
            e: `/edit/${encodeURIComponent(documentTitle)}`,
            d: `/discussion/${encodeURIComponent(documentTitle)}`,
            a: "/RandomPage",
            f: `/w/${encodeURIComponent(mainPage)}`,
            h: `/history/${encodeURIComponent(documentTitle)}`
        };
        const shortcut = event.key.toLowerCase();
        const destination = shortcuts[shortcut];
        const currentModes = {
            w: "w",
            e: "edit",
            d: "discussion",
            h: "history"
        };

        if (destination && currentModes[shortcut] !== pageMode) {
            const destinationUrl = new URL(destination, window.location.origin);
            if (destinationUrl.pathname !== window.location.pathname) {
                event.preventDefault();
                window.location.href = destination;
            }
        }
    });

    const protectBtn = document.getElementById("protect-btn");

    if (protectBtn) {
        const docTitle = protectBtn.getAttribute("data-doc");

        fetch(`/api/protect/${encodeURIComponent(docTitle)}`)
            .then(response => response.json())
            .then(data => {
                if (data.is_admin) {
                    protectBtn.style.display = "inline-block";
                    updateProtectButtonUI(protectBtn, data.is_protected);
                } else {
                    protectBtn.style.display = "none";
                }
            })
            .catch(err => console.error("보호 상태 로딩 실패:", err));

        protectBtn.addEventListener("click", function(e) {
            e.preventDefault();
            
            fetch(`/api/protect/${encodeURIComponent(docTitle)}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                }
            })
            .then(response => {
                if (response.status === 403) {
                    alert("권한이 없습니다.");
                    throw new Error("403 Forbidden");
                }
                return response.json();
            })
            .then(data => {
                if (data.status === "success") {
                    updateProtectButtonUI(protectBtn, data.is_protected);
                }
            })
            .catch(err => console.error("보호 토글 실패:", err));
        });
    }

    const directAddressEntry = !document.referrer || !document.referrer.startsWith(window.location.origin);
    const currentSearchQuery = new URLSearchParams(window.location.search).get("q") || "";

    document.querySelectorAll('form[action="/search"]').forEach(function(form) {
        const input = form.querySelector('input[name="q"]');
        if (!input) {
            return;
        }

        const tryExactDocumentRedirect = function() {
            const value = input.value.trim();
            if (!value) {
                return;
            }

            if (window.location.pathname === "/search" && currentSearchQuery && value === currentSearchQuery.trim()) {
                return;
            }

            if (directAddressEntry && window.location.pathname === "/search") {
                return;
            }

            fetch(`/api/document-exists/${encodeURIComponent(value)}`)
                .then(response => response.json())
                .then(data => {
                    if (data && data.exists && data.redirect) {
                        window.location.href = data.redirect;
                    }
                })
                .catch(function() {
                });
        };

        input.addEventListener("change", tryExactDocumentRedirect);
        input.addEventListener("keydown", function(event) {
            if (event.key === "Enter") {
                tryExactDocumentRedirect();
            }
        });
    });
});

function updateProtectButtonUI(btn, isProtected) {
    if (isProtected === 1) {
        btn.textContent = "보호 해제";
        btn.style.backgroundColor = "#d9534f";
        btn.style.color = "white";
    } else {
        btn.textContent = "보호";
        btn.style.backgroundColor = "#4CAF50";
        btn.style.color = "white";
    }
}