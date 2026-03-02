// Hamburger / mobile nav toggle
document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('nav-hamburger');
    var menu = document.getElementById('mobile-menu');
    var line1 = document.getElementById('hamburger-line-1');
    var line2 = document.getElementById('hamburger-line-2');
    var line3 = document.getElementById('hamburger-line-3');

    if (!btn || !menu) return;

    var open = false;

    function openMenu() {
        open = true;
        btn.setAttribute('aria-expanded', 'true');
        menu.classList.remove('hidden');
        line1.style.transform = 'translateY(8px) rotate(45deg)';
        line2.style.opacity = '0';
        line3.style.transform = 'translateY(-8px) rotate(-45deg)';
    }

    function closeMenu() {
        open = false;
        btn.setAttribute('aria-expanded', 'false');
        menu.classList.add('hidden');
        line1.style.transform = '';
        line2.style.opacity = '';
        line3.style.transform = '';
    }

    btn.addEventListener('click', function () {
        open ? closeMenu() : openMenu();
    });

    // Close menu when clicking a nav link
    menu.querySelectorAll('a').forEach(function (link) {
        link.addEventListener('click', closeMenu);
    });
});
