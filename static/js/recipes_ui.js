document.addEventListener('DOMContentLoaded', () => {
    // Handle "Add to Menu" / "Remove from Menu" toggle buttons
    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('.toggle-menu-btn');
        if (!btn) return;

        const recipeId = btn.dataset.id;
        if (!recipeId) return;

        // Visual feedback
        const originalHtml = btn.innerHTML;
        const originalClasses = btn.className;
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

            // Update button state
            if (data.is_on_menu) {
                btn.innerHTML = 'On Menu';
                btn.className = originalClasses.replace(/text-gray-400|border-gray-200|hover:border-\[#194769\]|hover:text-\[#194769\]|text-\[#194769\]|border-\[#194769\]/g, '').trim() + ' bg-[#5B8E7D] text-white border-[#5B8E7D]';
                // Also handle the hover state for detail view button
                if (btn.classList.contains('w-full')) {
                    btn.classList.add('hover:bg-[#194769]', 'hover:border-[#194769]');
                    btn.innerHTML = 'Remove from Menu';
                }
            } else {
                btn.innerHTML = btn.classList.contains('w-full') ? '+ Add to Menu' : '+ Add to Menu';
                btn.className = originalClasses.replace(/bg-\[#5B8E7D\]|text-white|border-\[#5B8E7D\]|hover:bg-\[#194769\]|hover:border-\[#194769\]/g, '').trim();

                if (btn.classList.contains('w-full')) {
                    btn.classList.add('text-[#194769]', 'border-[#194769]', 'hover:bg-[#194769]', 'hover:text-white');
                } else {
                    btn.classList.add('text-gray-400', 'border-gray-200', 'hover:border-[#194769]', 'hover:text-[#194769]');
                }
            }

            // Show toast if available (assuming some toast utility might exist or just alert)
            console.log(`${data.title} ${data.is_on_menu ? 'added to' : 'removed from'} menu`);

        } catch (err) {
            console.error(err);
            btn.innerHTML = originalHtml;
            btn.className = originalClasses;
            alert('Could not update menu status. Please try again.');
        } finally {
            btn.disabled = false;
        }
    });

    // Helper to get CSRF token
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
});
