document.addEventListener('DOMContentLoaded', () => {
    // Handle "Add to Menu" / "Remove from Menu" toggle buttons
    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('.toggle-menu-btn');
        if (!btn) return;

        const recipeId = btn.dataset.id;
        if (!recipeId) return;

        // Visual feedback
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="animate-pulse">Updating...</span>';
        btn.disabled = true;

        try {
            const response = await fetch('/api/recipes/toggle-menu/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({ recipe_id: recipeId })
            });

            if (!response.ok) throw new Error('Failed to toggle menu status');

            const data = await response.json();

            // Swap classes using data attributes set in the template
            const onClasses = (btn.dataset.onClasses || '').split(' ').filter(Boolean);
            const offClasses = (btn.dataset.offClasses || '').split(' ').filter(Boolean);

            if (data.is_on_menu) {
                btn.classList.remove(...offClasses);
                btn.classList.add(...onClasses);
                btn.textContent = btn.classList.contains('w-full') ? 'Remove from Menu' : 'On Menu';
            } else {
                btn.classList.remove(...onClasses);
                btn.classList.add(...offClasses);
                btn.textContent = '+ Add to Menu';
            }

            // Notify meal_plan.js (or any other listener) that the menu status changed
            btn.dispatchEvent(new CustomEvent('menuToggled', {
                bubbles: true,
                detail: { recipe_id: recipeId, is_on_menu: data.is_on_menu }
            }));

        } catch (err) {
            console.error(err);
            btn.innerHTML = originalHtml;
            showToast('Could not update menu status. Please try again.', 'error');
        } finally {
            btn.disabled = false;
        }
    });

    // Helper to get CSRF token from cookie
    function getCookie(name) {
        return document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))?.[1] ?? null;
    }

    // Non-blocking toast for error feedback (reuses message-item CSS already in base.html)
    function showToast(message, type = 'error') {
        const div = document.createElement('div');
        const colorClass = type === 'error'
            ? 'bg-red-50 text-red-800 border border-red-200'
            : 'bg-green-50 text-green-800 border border-green-200';
        div.className = `message-item fixed top-4 right-4 z-50 rounded-lg px-6 py-4 shadow-lg ${colorClass}`;
        div.textContent = message;
        document.body.appendChild(div);
        fadeOutMessage(div);
    }
});
