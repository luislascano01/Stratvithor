document.addEventListener('DOMContentLoaded', function() {
    // Function to toggle the sidebar (fully collapse/expand)
    window.toggleSidebar = function() {
        const sidebar = document.getElementById('sidebar');
        // If sidebar is expanded, collapse it; otherwise, expand it
        if (sidebar.classList.contains('expanded')) {
            sidebar.classList.remove('expanded');
            sidebar.classList.add('collapsed');
        } else {
            sidebar.classList.remove('collapsed');
            sidebar.classList.add('expanded');
        }
    };

    // Function to toggle dark mode on the entire page by toggling a class on <html>
    window.toggleDarkMode = function() {
        document.documentElement.classList.toggle('dark-mode');
        console.log('Dark mode toggled. Current <html> classes:', document.documentElement.className);
    };

    // Function to send a message and display it in the chat container
    window.sendMessage = function() {
        const input = document.getElementById('chat-input');
        const text = input.value.trim();
        if (!text) return;

        const chatContainer = document.getElementById('chat-container');
        const messageDiv = document.createElement('div');
        messageDiv.className = 'p-2 my-2 rounded w-fit bg-blue-500 text-white self-end';
        messageDiv.innerText = text;
        chatContainer.appendChild(messageDiv);

        input.value = '';
    };

    // Function to handle key events in the chat input
    window.handleKey = function(event) {
        if (event.key === 'Enter') {
            sendMessage();
        }
    };

    // Placeholder for newChat functionality
    window.newChat = function() {
        console.log("New chat triggered");
    };
});