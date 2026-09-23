document.addEventListener('DOMContentLoaded', function() {

    // 1. Whole Filter Box Toggle (Mobile & Desktop)
    const filterBoxToggle = document.getElementById('toggle-filters-box');
    const filterFormContainer = document.getElementById('filter-form-container');
    const filtersToggleText = document.getElementById('filters-toggle-text');
    const filtersToggleIcon = document.getElementById('filters-toggle-icon');

    if (filterBoxToggle && filterFormContainer && filtersToggleText && filtersToggleIcon) {
        function updateToggleState(isOpen) {
            if (isOpen) {
                filterFormContainer.style.display = 'block';
                filterFormContainer.classList.remove('hidden');
                filtersToggleText.textContent = 'Hide';
                filtersToggleIcon.style.transform = 'rotate(180deg)';
            } else {
                filterFormContainer.style.display = 'none';
                filterFormContainer.classList.add('hidden');
                filtersToggleText.textContent = 'Show';
                filtersToggleIcon.style.transform = 'rotate(0deg)';
            }
        }

        // Initialize state on page load: desktop starts open, mobile starts closed
        const mediaQuery = window.matchMedia('(min-width: 1024px)');
        updateToggleState(mediaQuery.matches);

        // Auto-adapt on screen resize between mobile and desktop
        if (mediaQuery.addEventListener) {
            mediaQuery.addEventListener('change', function(e) {
                updateToggleState(e.matches);
            });
        }

        filterBoxToggle.addEventListener('click', function(e) {
            if (e.target.closest('#filter-form-container')) return;

            const isCurrentlyOpen = filterFormContainer.style.display === 'block' ||
                (!filterFormContainer.classList.contains('hidden') && window.getComputedStyle(filterFormContainer).display !== 'none');

            updateToggleState(!isCurrentlyOpen);
        });
    }

    // 2. Tag section toggle inside filters
    const toggleButton = document.getElementById('toggle-tags');
    const tagsContainer = document.getElementById('tags-container');
    const toggleText = document.getElementById('toggle-text');
    const toggleIcon = document.getElementById('toggle-icon');

    // Only run if the elements exist
    if (!toggleButton || !tagsContainer || !toggleText || !toggleIcon) {
        return;
    }

    // Check if any tags are selected on page load
    const selectedTags = document.querySelectorAll('input[name="tags"]:checked');
    if (selectedTags.length > 0) {
        tagsContainer.classList.remove('hidden');
        toggleText.textContent = 'Hide';
        toggleIcon.style.transform = 'rotate(180deg)';
    }

    toggleButton.addEventListener('click', function(e) {
        e.stopPropagation();
        const isHidden = tagsContainer.classList.contains('hidden');

        if (isHidden) {
            tagsContainer.classList.remove('hidden');
            toggleText.textContent = 'Hide';
            toggleIcon.style.transform = 'rotate(180deg)';
        } else {
            tagsContainer.classList.add('hidden');
            toggleText.textContent = 'Show';
            toggleIcon.style.transform = 'rotate(0deg)';
        }
    });
});
