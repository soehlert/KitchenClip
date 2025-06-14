let availableTags = [];
let selectedTags = [];
const tagInput = document.getElementById('tag-input');
const tagInputContainer = document.getElementById('tag-input-container');
const hiddenTagsInput = document.getElementById('hidden-tags-input');
const suggestions = document.getElementById("tag-suggestions");
let highlightedIndex = -1;

function renderTags() {
  tagInputContainer.querySelectorAll('.tag-badge').forEach(el => el.remove());
  selectedTags.forEach(tag => {
    const badge = document.createElement('span');
    badge.className = 'tag-badge inline-block text-white text-xs px-2 py-1 rounded-full mr-2 mb-2';
    badge.style.backgroundColor = tag.color || '#888';
    badge.textContent = tag.name;
    const removeBtn = document.createElement('span');
    removeBtn.className = 'ml-2 cursor-pointer font-bold';
    removeBtn.textContent = '×';
    removeBtn.onclick = () => {
      selectedTags = selectedTags.filter(t => t.name !== tag.name);
      renderTags();
    };
    badge.appendChild(removeBtn);
    tagInputContainer.insertBefore(badge, tagInput);
  });
  hiddenTagsInput.value = selectedTags.map(t => t.name).join(', ');
}

function addTag(name, color) {
  if (!name) return;
  if (!selectedTags.some(t => t.name.toLowerCase() === name.toLowerCase())) {
    selectedTags.push({name, color: color || "#888"});
    renderTags();
  }
  tagInput.value = '';
  suggestions.style.display = "none";
  highlightedIndex = -1;
}

tagInput.addEventListener("input", function() {
  const val = tagInput.value.trim().toLowerCase();
  suggestions.innerHTML = "";
  highlightedIndex = -1;
  if (val.length >= 2) {
    fetch(suggestions.dataset.autocompleteUrl + "?q=" + encodeURIComponent(val))
    .then(response => response.json())
    .then(data => {
      // Filter out already-selected tags
      const filtered = data.filter(tag =>
        !selectedTags.some(t => t.name.toLowerCase() === tag.name.toLowerCase())
      );
      if (filtered.length > 0) {
        filtered.forEach((tag, idx) => {
          const li = document.createElement("li");
          li.innerHTML = `<span class="inline-block text-white text-xs px-2 py-1 rounded-full mr-2 mb-2" style="background:${tag.color};">${tag.name}</span>`;
          li.className = "px-3 py-2 cursor-pointer flex items-center";
          li.onclick = function() {
            addTag(tag.name, tag.color);
            tagInput.focus();
          };
          suggestions.appendChild(li);
        });
        suggestions.style.display = "block";
      } else {
        suggestions.style.display = "none";
      }
    });
  } else {
    suggestions.style.display = "none";
  }
});

tagInput.addEventListener('keydown', function(e) {
  const items = suggestions.querySelectorAll("li");
  if (suggestions.style.display === "block" && items.length > 0) {
    if (e.key === "ArrowDown" || (e.key === "Tab" && !e.shiftKey)) {
      e.preventDefault();
      highlightedIndex = (highlightedIndex + 1) % items.length;
      items.forEach((li, idx) => li.classList.toggle("bg-gray-200", idx === highlightedIndex));
      return;
    } else if (e.key === "ArrowUp" || (e.key === "Tab" && e.shiftKey)) {
      e.preventDefault();
      highlightedIndex = (highlightedIndex - 1 + items.length) % items.length;
      items.forEach((li, idx) => li.classList.toggle("bg-gray-200", idx === highlightedIndex));
      return;
    } else if (e.key === "Enter" && highlightedIndex >= 0) {
      e.preventDefault();
      items[highlightedIndex].click();
      highlightedIndex = -1;
      return;
    } else if (e.key === "Enter" && items.length === 1) {
      e.preventDefault();
      items[0].click();
      highlightedIndex = -1;
      return;
    }
  }
  if ((e.key === 'Enter' || e.key === ',') && (highlightedIndex === -1 || items.length === 0)) {
    e.preventDefault();
    const val = tagInput.value.trim();
    if (val) {
      const found = availableTags.find(t => t.name.toLowerCase() === val.toLowerCase());
      addTag(val, found ? found.color : "#888");
    }
  }
});

tagInput.addEventListener('keydown', function(e) {
  if (e.key === 'Backspace' && !tagInput.value && selectedTags.length) {
    selectedTags.pop();
    renderTags();
  }
});

document.addEventListener("click", function(e) {
  if (!suggestions.contains(e.target) && e.target !== tagInput) {
    suggestions.style.display = "none";
    highlightedIndex = -1;
  }
});

document.addEventListener('DOMContentLoaded', function() {
  availableTags = window.availableTags || [];
  const initial = hiddenTagsInput.value.split(',').map(s => s.trim()).filter(Boolean);
  selectedTags = initial.map(name => {
    const found = availableTags.find(t => t.name.toLowerCase() === name.toLowerCase());
    return {name, color: found ? found.color : "#888"};
  });
  renderTags();
});

document.querySelector('form').addEventListener('submit', function(e) {
  const val = tagInput.value.trim();
  if (val) {
    const found = availableTags.find(t => t.name.toLowerCase() === val.toLowerCase());
    addTag(val, found ? found.color : "#888");
  }
  selectedTags = selectedTags.filter(t => t.name && t.name.trim());
  renderTags();
});
