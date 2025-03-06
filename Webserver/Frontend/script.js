document.addEventListener('DOMContentLoaded', function () {
    // Debug: Check for critical elements
    const chatContainer = document.getElementById('chat-container');
    if (!chatContainer) {
        console.error("Error: Element with id 'chat-container' not found in the DOM.");
    } else {
        console.log("'chat-container' element found.");
    }

    // ----- Sidebar Toggle -----
    window.toggleSidebar = function () {
        const sidebar = document.getElementById('sidebar');
        sidebar.classList.toggle('collapsed');
        sidebar.classList.toggle('expanded');
    };

    // ----- Dark Mode Toggle -----
    window.toggleDarkMode = function () {
        document.documentElement.classList.toggle('dark-mode');
    };

    // ----- New Chat Handler -----
    window.newChat = function () {
        console.log("New chat triggered");
    };

    // ----- Handle 'Enter' Key in Input -----
    window.handleKey = function (event) {
        if (event.key === 'Enter') {
            initiateReport();

        }
    };

    // Fetch and populate the prompt set dropdown
    const promptSelector = document.getElementById('prompt-set-selector');

    async function loadPromptSets() {
        try {
            const response = await fetch("/reportComposerAPI/get_prompts");
            if (!response.ok) throw new Error("Failed to fetch prompts");

            const promptFiles = await response.json(); // List of prompt filenames
            promptSelector.innerHTML = ""; // Clear existing options

            // Populate dropdown with filenames (remove extensions and paths)
            promptFiles.forEach(file => {
                const fileName = file.replace(/^.*[\\/]/, '').replace(/\.[^/.]+$/, ""); // Remove path and extension
                const option = document.createElement("option");
                option.value = file; // Store actual filename
                option.textContent = fileName; // Display clean name
                promptSelector.appendChild(option);
            });
        } catch (error) {
            console.error("Error loading prompt sets:", error);
            promptSelector.innerHTML = "<option>Error loading prompts</option>";
        }
    }

    // Call this function on page load
    loadPromptSets();

    // Handle dropdown selection
    promptSelector.addEventListener('change', async function () {
        const selectedPrompt = this.value;
        if (!selectedPrompt) return;

        try {
            const updateResponse = await fetch("/reportComposerAPI/update_prompt", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({yaml_file_path: selectedPrompt}),
            });

            if (!updateResponse.ok) throw new Error("Failed to update prompt");
            console.log("Prompt updated to:", selectedPrompt);
        } catch (error) {
            console.error("Error updating prompt set:", error);
        }
    });


    let zoom = d3.zoom()
        .scaleExtent([0.5, 3]) // Set zoom limits
        .on("zoom", function (event) {
            g.attr("transform", event.transform);
        });


    // ----- Initiate Report Generation -----
    window.initiateReport = async function () {
        const input = document.getElementById('chat-input');
        const companyName = input.value.trim();
        if (!companyName) return;

        const chatContainer = document.getElementById('chat-container');
        if (!chatContainer) {
            console.error("Cannot find 'chat-container'. Please check your HTML.");
            return;
        }

        // Get the selected prompt from the dropdown
        const promptSelector = document.getElementById('prompt-set-selector');
        const selectedPrompt = promptSelector.value;

        if (!selectedPrompt) {
            console.error("No prompt set selected.");
            return;
        }

        // Show user message
        const messageDiv = document.createElement('div');
        messageDiv.className = 'p-2 my-2 rounded w-fit bg-blue-500 text-white self-end';
        messageDiv.innerText = `Generating report for: ${companyName} (Prompt: ${selectedPrompt})`;
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
                    mock: true,
                    prompt_name: selectedPrompt  // Include the selected prompt
                })
            });

            if (!response.ok) throw new Error("Request failed with status " + response.status);

            const data = await response.json();
            const taskId = data.task_id;

            document.getElementById('chat-input-panel').classList.add('hidden');
            document.getElementById('dag-updates-container').classList.remove('hidden');

            openWebSocketForTask(taskId);

        } catch (err) {
            console.error("Error generating report:", err);
            const errorDiv = document.createElement('div');
            errorDiv.className = 'p-2 my-2 rounded bg-red-600 text-white';
            errorDiv.innerText = "Failed to start report: " + err.message;
            chatContainer.appendChild(errorDiv);
        }
    };


    // -----------------------------------------------------------------
    // D3.js Graph Visualization with scrolling, zooming, and auto-center
    // -----------------------------------------------------------------
    const svg = d3.select("#dag-svg")
        .attr("viewBox", "-500 -500 1000 1000")
        .attr("preserveAspectRatio", "xMidYMid meet");

    const g = svg.append("g"); // Group for zoom and pan

    const width = 1000;
    const height = 1000;
    let simulation, linkSelection, nodeSelection;
    let nodes = [];
    let links = [];

    function initGraph(dagData) {
        nodes = dagData.nodes;
        links = dagData.links;

        simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(links).id(d => d.id).distance(120))
            .force("charge", d3.forceManyBody().strength(-300))
            .force("center", d3.forceCenter(0, 0))  // Center at 0,0 for scrolling
            .force("collide", d3.forceCollide().radius(30));

        // Draw links
        linkSelection = g.append("g")
            .attr("class", "links")
            .selectAll("line")
            .data(links)
            .enter().append("line")
            .attr("stroke", "#999")
            .attr("stroke-width", 2);

        // Draw nodes
        nodeSelection = g.append("g")
            .attr("class", "nodes")
            .selectAll("circle")
            .data(nodes)
            .enter().append("circle")
            .attr("r", 20)
            .attr("fill", "#ccc")
            .attr("stroke", "#333")
            .attr("stroke-width", 1.5);

        // Tooltips
        nodeSelection.append("title").text(d => d.label);

        // Enable dragging
        nodeSelection.call(d3.drag()
            .on("start", dragstarted)
            .on("drag", dragged)
            .on("end", dragended));

        simulation.on("tick", () => {
            linkSelection
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);

            nodeSelection
                .attr("cx", d => d.x)
                .attr("cy", d => d.y);
        });

        // ✅ Call autoCenterGraph only after the simulation stabilizes
        simulation.on("end", () => {
            console.log("Graph simulation stabilized. Auto-centering...");
            autoCenterGraph();
        });

        // Enable zoom and pan
        svg.call(d3.zoom()
            .scaleExtent([0.5, 3])
            .on("zoom", function (event) {
                g.attr("transform", event.transform);
            }));
    }


    function autoCenterGraph() {
        if (nodes.length === 0) return;

        const minX = d3.min(nodes, d => d.x);
        const maxX = d3.max(nodes, d => d.x);
        const minY = d3.min(nodes, d => d.y);
        const maxY = d3.max(nodes, d => d.y);

        const graphWidth = maxX - minX;
        const graphHeight = maxY - minY;

        const centerX = minX + graphWidth / 1;
        const centerY = minY + graphHeight / 1;

        const scale = Math.min(
            width / (graphWidth * 2),  // Scale to fit width
            height / (graphHeight * 2) // Scale to fit height
        );

        // Apply zoom and pan transformation
        svg.transition()
            .duration(750)
            .call(
                zoom.transform,
                d3.zoomIdentity
                    .translate(width / 5, height / 5)
                    .scale(scale)
                    .translate(-centerX, -centerY)
            );
    }

    // Drag event handlers
    function dragstarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }

    function dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }

    function dragended(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }

    // ----- WebSocket Handling for Real-Time Updates -----
    function openWebSocketForTask(taskId) {
        const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${wsProtocol}//${window.location.host}/reportComposerAPI/ws/${taskId}`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => console.log("WebSocket connected for task ID:", taskId);

        ws.onmessage = event => {
            const message = JSON.parse(event.data);
            if (message.type === "init") initGraph(message.dag);
            else if (message.type === "update") updateNodeStatus(message.node_id, message.status, message.result);
        };

        ws.onclose = () => console.log("WebSocket closed for task:", taskId);
        ws.onerror = err => console.error("WebSocket error:", err);
    }

    // ----- Node Status Updates with Breathing Animation -----
    function updateNodeStatus(nodeId, status, result) {
        const node = nodes.find(n => n.id == nodeId);
        if (!node) return;

        let newColor = "#ccc";
        if (status === "processing") {
            newColor = "#FFD700"; // yellow
            svg.selectAll("circle")
                .filter(d => d.id == nodeId)
                .classed("breathing", true);
        } else if (status === "complete") {
            newColor = "#32CD32"; // green
            svg.selectAll("circle")
                .filter(d => d.id == nodeId)
                .classed("breathing", false);
        } else if (status === "failed") {
            newColor = "#FF4500"; // orange-red
            svg.selectAll("circle")
                .filter(d => d.id == nodeId)
                .classed("breathing", false);
        }

        svg.selectAll("circle")
            .filter(d => d.id == nodeId)
            .transition().duration(500)
            .attr("fill", newColor);
    }

    // Add auto-center button
    const centerBtn = document.createElement("button");
    centerBtn.innerText = "Auto-Center";
    centerBtn.className = "p-2 bg-blue-500 text-white rounded";
    centerBtn.onclick = autoCenterGraph;
    document.getElementById("dag-updates-container").prepend(centerBtn);
});

window.toggleChatHistory = function () {
    const sidebar = document.getElementById('sidebar');
    const toggleButton = document.getElementById('toggle-sidebar-btn');

    // Toggle hidden class
    sidebar.classList.toggle('hidden');

    // Optionally change button text
    if (sidebar.classList.contains('hidden')) {
        toggleButton.innerText = "📂 Show Chat History";
    } else {
        toggleButton.innerText = "📂 Hide Chat History";
    }
};
