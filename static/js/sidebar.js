document.addEventListener('DOMContentLoaded', function() {

    // 1. Whole Filter Box Toggle (Mobile & Desktop)
    const filterBoxToggle = document.getElementById('toggle-filters-box');
    const filterFormContainer = document.getElementById('filter-form-container');
    const filtersToggleText = document.getElementById('filters-toggle-text');
    const filtersToggleIcon = document.getElementById('filters-toggle-icon');

    if (filterBoxToggle && filterFormContainer && filtersToggleText && filtersToggleIcon) {
        filterBoxToggle.addEventListener('click', function(e) {
            if (e.target.closest('#filter-form-container')) return;

            const isHidden = filterFormContainer.classList.contains('hidden') ||
                             (window.getComputedStyle(filterFormContainer).display === 'none');

            if (isHidden) {
                filterFormContainer.classList.remove('hidden');
                filterFormContainer.classList.add('block');
                filterFormContainer.classList.remove('lg:hidden');
                filtersToggleText.innerHTML = 'Hide';
                filtersToggleIcon.classList.add('rotate-180');
                filtersToggleIcon.classList.remove('rotate-0');
            } else {
                filterFormContainer.classList.add('hidden');
                filterFormContainer.classList.remove('block');
                filterFormContainer.classList.remove('lg:block');
                filtersToggleText.innerHTML = 'Show';
                filtersToggleIcon.classList.remove('rotate-180');
                filtersToggleIcon.classList.add('rotate-0');
            }
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
