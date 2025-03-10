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
                    mock: mock_global,
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

        // Draw nodes and add click listener
        nodeSelection = g.append("g")
            .attr("class", "nodes")
            .selectAll("circle")
            .data(nodes)
            .enter().append("circle")
            .attr("r", 20)
            .attr("fill", "#ccc")
            .attr("stroke", "#333")
            .attr("stroke-width", 1.5)
            .on("click", (event, d) => {
                // On click, fetch the node details from the global store
                const details = nodeDetails[d.id];
                if (details) {
                    displayNodeDetails(d.id, details);
                }
            });

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
            else if (message.type === "update") {
                updateNodeStatus(message.node_id, message.status, message.result);
                nodeDetails[message.node_id] = {
                    status: message.status,
                    result: message.result
                };
            }


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
}


const nodeDetails = {};
function displayNodeDetails(nodeId, details) {
    const chatHistory = document.getElementById("node-view");
    // Clear any existing content
    chatHistory.innerHTML = "";

    // 1) Create a header for the node number
    const nodeHeader = document.createElement("h3");
    nodeHeader.className = "text-base font-semibold mb-1";
    nodeHeader.innerText = `Node ${nodeId}`;

    // 2) Show status
    const statusPara = document.createElement("p");
    statusPara.className = "text-sm text-gray-300 mb-3";
    statusPara.innerText = `Status: ${details.status}`;

    // 3) Safely parse the node's result into an object
    let resultObj = details.result;
    if (typeof resultObj === "string") {
        try {
            resultObj = JSON.parse(resultObj);
        } catch (err) {
            console.warn("Result is not valid JSON, using raw string.");
        }
    }
    resultObj = resultObj || {};

    // 4) Extract relevant fields
    const sectionTitle = resultObj.section_title || resultObj.section_tile || "Untitled Section";
    // If there's no LLM response, we can still display other text (like online data).
    // So we'll handle that gracefully:
    let llmResponse = resultObj.llm;
    if (!llmResponse) {
        llmResponse = "No LLM response found.";  // fallback text
    }

    const onlineData = resultObj.online_data || "No online data found.";

    // 5) Section Title in large bold letters
    const sectionTitleEl = document.createElement("h2");
    sectionTitleEl.className = "text-lg font-bold mb-2";
    sectionTitleEl.innerText = sectionTitle;

    // 6) Create a separator
    const separator1 = document.createElement("hr");
    separator1.className = "my-2 border-gray-500";

    // 7) Convert LLM response from markdown to HTML
    const llmDiv = document.createElement("div");
    llmDiv.className = "whitespace-pre-wrap mb-4";

    // If llmResponse is not a string (e.g. an object), convert to a JSON string
    let finalMarkdown = llmResponse;
    if (typeof llmResponse !== "string") {
        finalMarkdown = JSON.stringify(llmResponse, null, 2);
    }

    // Create a custom renderer to ensure headings are at least <h4>
    const renderer = new marked.Renderer();
    renderer.heading = function (text, level, raw, slugger) {
        // If level is not a valid number, default to 4
        if (!level || isNaN(level)) {
            level = 4;
        } else {
            level = Math.max(level, 4);
        }
        return `<h${level}>${text}</h${level}>`;
    };

    const htmlContent = marked.parse(finalMarkdown, { renderer });
    llmDiv.innerHTML = htmlContent;

    // 8) Another separator
    const separator2 = document.createElement("hr");
    separator2.className = "my-2 border-gray-500";

    // 9) Online data at the end
    const onlineDataDiv = document.createElement("div");
    onlineDataDiv.className = "text-sm text-gray-300 whitespace-pre-wrap";
    onlineDataDiv.innerText = `Online Data:\n${onlineData}`;

    // 10) Append all elements to the node-view container
    chatHistory.appendChild(nodeHeader);
    chatHistory.appendChild(statusPara);
    chatHistory.appendChild(sectionTitleEl);
    chatHistory.appendChild(separator1);
    chatHistory.appendChild(llmDiv);
    chatHistory.appendChild(separator2);
    chatHistory.appendChild(onlineDataDiv);
}

document.addEventListener('DOMContentLoaded', function () {
    // ... existing code ...

    // ----- Separator Drag Functionality for Sidebar Resizing -----
    const separator = document.getElementById('separator');
    const sidebar = document.getElementById('sidebar');
    let isDragging = false;

    separator.addEventListener('mousedown', function (e) {
        isDragging = true;
        document.body.style.cursor = 'ew-resize';
    });

    document.addEventListener('mousemove', function (e) {
        if (!isDragging) return;
        let newWidth = e.clientX;
        newWidth = Math.max(newWidth, 150); // Minimum sidebar width

        // If you want no maximum at all, remove the line below:
        // newWidth = Math.min(newWidth, 500);

        // If you prefer to keep a small margin on the right:
        // const maxWidth = window.innerWidth - 50; // 50px margin
        // newWidth = Math.min(newWidth, maxWidth);

        sidebar.style.width = newWidth + 'px';
    });

    document.addEventListener('mouseup', function (e) {
        if (isDragging) {
            isDragging = false;
            document.body.style.cursor = 'default';
        }
    });

    // ... rest of your existing code ...
});

// Initialize global variable
window.mock_global = false;

// Define a function to toggle the variable and update the button text
window.toggleMock = function () {
    window.mock_global = !window.mock_global;
    const btn = document.getElementById("toggle-mock-button");
    btn.innerText = "Mock: " + (window.mock_global ? "ON" : "OFF");
    console.log("mock_global toggled: " + window.mock_global);
};

document.addEventListener('DOMContentLoaded', function () {
    // Existing code...

    // Create the toggle button element
    const toggleMockButton = document.createElement("button");
    toggleMockButton.id = "toggle-mock-button";
    toggleMockButton.innerText = "Mock: OFF"; // Initial text when mock_global is false
    toggleMockButton.className = "p-2 bg-green-500 text-white rounded m-2";

    // Append the button to an appropriate container.
    // Here, we append it to the user-info container if available; otherwise, to the body.
    const userInfoDiv = document.querySelector('.user-info');
    if (userInfoDiv) {
        userInfoDiv.appendChild(toggleMockButton);
    } else {
        document.body.appendChild(toggleMockButton);
    }

    // Add click listener to toggle the global variable
    toggleMockButton.addEventListener('click', window.toggleMock);

    // ... rest of your existing code ...
});

