// Auto-dismiss messages functionality
document.addEventListener('DOMContentLoaded', function() {
    const messages = document.querySelectorAll('.message-item');

    messages.forEach(function(message) {
        setTimeout(function() {
            fadeOutMessage(message);
        }, 3000);
    });
});

function fadeOutMessage(element) {
    element.style.transition = 'opacity 0.5s ease-out';
    element.style.opacity = '0';

    setTimeout(function() {
        element.remove();
    }, 500);
}

function dismissMessage(button) {
    const message = button.closest('.message-item');
    fadeOutMessage(message);
}