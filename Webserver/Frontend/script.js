document.addEventListener('DOMContentLoaded', function() {
  // ----- Sidebar Toggle -----
  window.toggleSidebar = function() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar.classList.contains('expanded')) {
      sidebar.classList.remove('expanded');
      sidebar.classList.add('collapsed');
    } else {
      sidebar.classList.remove('collapsed');
      sidebar.classList.add('expanded');
    }
  };

  // ----- Dark Mode -----
  window.toggleDarkMode = function() {
    document.documentElement.classList.toggle('dark-mode');
    console.log('Dark mode toggled. Current <html> classes:', document.documentElement.className);
  };

  // ----- New Chat -----
  window.newChat = function() {
    console.log("New chat triggered");
    // Could reset UI or create a new session, etc.
  };

  // ----- Handle Key (Enter) -----
  window.handleKey = function(event) {
    if (event.key === 'Enter') {
      initiateReport();
    }
  };

  // ----- Initiate Report Generation -----
  window.initiateReport = async function() {
    const input = document.getElementById('chat-input');
    const companyName = input.value.trim();
    if (!companyName) return;

    // Show the user's typed message in the chat container
    const chatContainer = document.getElementById('chat-container');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'p-2 my-2 rounded w-fit bg-blue-500 text-white self-end';
    messageDiv.innerText = "Generating report for: " + companyName;
    chatContainer.appendChild(messageDiv);

    // Call the FastAPI endpoint via the Nginx proxy (relative URL)
    try {
      const response = await fetch("/reportComposerAPI/generate_report", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": "your-secure-api-key" // if your server requires it
        },
        body: JSON.stringify({
          company_name: companyName,
          mock: true // or false to run real mode
        })
      });

      if (!response.ok) {
        throw new Error("Request failed with status " + response.status);
      }

      const data = await response.json();
      const taskId = data.task_id;

      // Hide input panel, show the DAG container
      document.getElementById('chat-input-panel').classList.add('hidden');
      document.getElementById('dag-updates-container').classList.remove('hidden');

      // Indicate the Task ID
      const updatesDiv = document.getElementById('dag-updates');
      const notice = document.createElement('div');
      notice.className = 'p-2 bg-gray-300 rounded';
      notice.innerText = `Task ID: ${taskId} - Waiting for updates...`;
      updatesDiv.appendChild(notice);

      // Open WebSocket to receive node-by-node updates using a relative URL
      openWebSocketForTask(taskId);

    } catch (err) {
      console.error("Error generating report:", err);
      const errorDiv = document.createElement('div');
      errorDiv.className = 'p-2 my-2 rounded bg-red-600 text-white';
      errorDiv.innerText = "Failed to start report: " + err.message;
      chatContainer.appendChild(errorDiv);
    }
  };

  // ----- Open WebSocket to listen for DAG updates using a relative URL -----
  async function openWebSocketForTask(taskId) {
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    // Build relative URL using the current host and the proxy path (/reportComposerAPI/)
    const wsUrl = `${wsProtocol}//${window.location.host}/reportComposerAPI/ws/${taskId}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = function() {
      console.log("WebSocket connected for task ID:", taskId);
    };

    ws.onmessage = function(event) {
      const updateData = JSON.parse(event.data);
      // updateData has: { task_id, node_id, status, result }
      const updatesDiv = document.getElementById('dag-updates');

      const line = document.createElement('div');
      line.className = "p-2 rounded bg-white shadow";
      line.innerHTML = `
        <strong>Node #${updateData.node_id}:</strong> 
        Status = ${updateData.status}.
        <br/> 
        Result: ${updateData.result}
      `;
      updatesDiv.appendChild(line);
    };

    ws.onclose = function() {
      console.log("WebSocket closed for task:", taskId);
      const updatesDiv = document.getElementById('dag-updates');
      const closeMsg = document.createElement('div');
      closeMsg.className = "p-2 mt-2 bg-gray-400 text-white rounded";
      closeMsg.innerText = "WebSocket connection closed.";
      updatesDiv.appendChild(closeMsg);
    };

    ws.onerror = function(err) {
      console.error("WebSocket error:", err);
    };
  }

  // If you still want a standard sendMessage for normal chat, you can do so:
  window.sendMessage = function() {
    // Currently replaced by "initiateReport()" for the form submission
  };
});