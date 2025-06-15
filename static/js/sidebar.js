document.addEventListener('DOMContentLoaded', function() {

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

    toggleButton.addEventListener('click', function() {
        const isHidden = tagsContainer.classList.contains('hidden');

        if (isHidden) {
            tagsContainer.classList.remove('hidden');
            toggleText.textContent = 'Hide';
            toggleIcon.style.transform = 'rotate(180deg)';
        } else {
            tagsContainer.classList.add('hidden');
            toggleText.textContent = 'Show';
            toggleIcon.style.transform = 'rotate(90deg)';
        }
    });
});
