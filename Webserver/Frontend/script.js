document.addEventListener('DOMContentLoaded', function() {
  // Debug: Check for critical elements
  const chatContainer = document.getElementById('chat-container');
  if (!chatContainer) {
    console.error("Error: Element with id 'chat-container' not found in the DOM.");
  } else {
    console.log("'chat-container' element found.");
  }

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

  // ----- Dark Mode Toggle -----
  window.toggleDarkMode = function() {
    document.documentElement.classList.toggle('dark-mode');
  };

  // ----- New Chat Handler -----
  window.newChat = function() {
    console.log("New chat triggered");
    // Could reset UI or create a new session, etc.
  };

  // ----- Handle 'Enter' Key in Input -----
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

    // Try to get the chat-container; log an error if not found.
    const chatContainer = document.getElementById('chat-container');
    if (!chatContainer) {
      console.error("Cannot find 'chat-container'. Please check your HTML.");
      return;
    }

    // Show the user's typed message in the chat container
    const messageDiv = document.createElement('div');
    messageDiv.className = 'p-2 my-2 rounded w-fit bg-blue-500 text-white self-end';
    messageDiv.innerText = "Generating report for: " + companyName;
    chatContainer.appendChild(messageDiv);

    try {
      const response = await fetch("/reportComposerAPI/generate_report", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": "your-secure-api-key"
        },
        body: JSON.stringify({
          company_name: companyName,
          mock: true // set to false for real mode
        })
      });

      if (!response.ok) {
        throw new Error("Request failed with status " + response.status);
      }

      const data = await response.json();
      const taskId = data.task_id;

      // Hide text input and show the DAG view
      document.getElementById('chat-input-panel').classList.add('hidden');
      document.getElementById('dag-updates-container').classList.remove('hidden');

      // Open the WebSocket for live DAG updates
      openWebSocketForTask(taskId);

    } catch (err) {
      console.error("Error generating report:", err);

      // Show an error message in the chat
      if (chatContainer) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'p-2 my-2 rounded bg-red-600 text-white';
        errorDiv.innerText = "Failed to start report: " + err.message;
        chatContainer.appendChild(errorDiv);
      }
    }
  };

  // ----- D3.js Graph Visualization -----
  let svg = d3.select("#dag-svg");
  const width = +svg.attr("width");
  const height = +svg.attr("height");

  let simulation;
  let linkSelection, nodeSelection;
  let nodes = [];
  let links = [];

  function initGraph(dagData) {
    nodes = dagData.nodes;
    links = dagData.links;

    simulation = d3.forceSimulation(nodes)
        .force("link", d3.forceLink(links).id(d => d.id).distance(120))
        .force("charge", d3.forceManyBody().strength(-300))
        .force("center", d3.forceCenter(width / 2, height / 2));

    // Draw links
    linkSelection = svg.append("g")
        .attr("class", "links")
        .selectAll("line")
        .data(links)
        .enter().append("line")
        .attr("stroke", "#999")
        .attr("stroke-width", 2);

    // Draw nodes
    nodeSelection = svg.append("g")
        .attr("class", "nodes")
        .selectAll("circle")
        .data(nodes)
        .enter().append("circle")
        .attr("r", 20)
        .attr("fill", "#ccc") // initial color (pending)
        .attr("stroke", "#333")
        .attr("stroke-width", 1.5)
        .append("title")
        .text(d => d.label);

    simulation.on("tick", () => {
      linkSelection
          .attr("x1", d => d.source.x)
          .attr("y1", d => d.source.y)
          .attr("x2", d => d.target.x)
          .attr("y2", d => d.target.y);

      // Update circle positions
      svg.selectAll("circle")
          .attr("cx", d => d.x)
          .attr("cy", d => d.y);
    });
  }

  function updateNodeStatus(nodeId, status, result) {
    // Update the node's status in our local data array
    const node = nodes.find(n => n.id == nodeId);
    if (!node) return;

    node.status = status;

    let newColor = "#ccc"; // default color for "pending"
    if (status === "processing") {
      newColor = "#FFD700"; // gold
      svg.selectAll("circle")
          .filter(d => d.id == nodeId)
          .classed("breathing", true);
    } else if (status === "complete") {
      newColor = "#32CD32"; // limegreen
      svg.selectAll("circle")
          .filter(d => d.id == nodeId)
          .classed("breathing", false);
    } else if (status === "failed") {
      newColor = "#FF4500"; // orange-red
      svg.selectAll("circle")
          .filter(d => d.id == nodeId)
          .classed("breathing", false);
    }

    // Animate fill color transition
    svg.selectAll("circle")
        .filter(d => d.id == nodeId)
        .transition().duration(500)
        .attr("fill", newColor);
  }

  // ----- Open WebSocket for DAG Updates -----
  function openWebSocketForTask(taskId) {
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${window.location.host}/reportComposerAPI/ws/${taskId}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = function() {
      console.log("WebSocket connected for task ID:", taskId);
    };

    ws.onmessage = function(event) {
      const message = JSON.parse(event.data);
      if (message.type === "init") {
        // Initialize the graph with the full DAG structure
        initGraph(message.dag);
      } else if (message.type === "update") {
        // Update a node's status (processing, complete, failed, etc.)
        updateNodeStatus(message.node_id, message.status, message.result);
      }
    };

    ws.onclose = function() {
      console.log("WebSocket closed for task:", taskId);
    };

    ws.onerror = function(err) {
      console.error("WebSocket error:", err);
    };
  }

  // If you still want a standard sendMessage for normal chat, do so:
  window.sendMessage = function() {
    // No-op in this example
  };
});