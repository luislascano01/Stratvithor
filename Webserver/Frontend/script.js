// =============================
// PART 1 OF 2
// =============================

// Global Variables and Basic Setup
window.web_search_enabled = true;
window.mock_global = false;
let nodes = [];
const nodeDetails = {};  // Store node statuses and results
let svg, g, zoom;
const width = 1000, height = 1000;
let simulation, linkSelection, nodeSelection;
let links = [];

// Global variable to hold current task ID
window.currentTaskId = null;

// --- loadPreviousReport ---
// This function fetches a saved task, extracts the stored DAG (saved as "dag" in report_data),
// and calls initGraph to reinitialize the D3 view.
async function loadPreviousReport(taskId) {
    try {
        if (!taskId) {
            alert("Please enter a Task ID.");
            return;
        }
        const response = await fetch(`/reportComposerAPI/get_saved_task/${taskId}`);
        if (!response.ok) {
            throw new Error(`Task not found or an error occurred. (HTTP ${response.status})`);
        }
        const data = await response.json();
        console.log("Loaded saved task data:", data);
        const savedDAG = data.report_data && data.report_data.dag;
        console.log("DAG portion of loaded data:", savedDAG);
        if (!savedDAG) {
            alert("No DAG structure found in the saved report.");
            return;
        }
        document.getElementById('chat-input-panel').classList.add('hidden');
        const dagContainer = document.getElementById('dag-updates-container');
        dagContainer.classList.remove('hidden');
        d3.select("#dag-svg").select("g").remove();
        initGraph(savedDAG);
        console.log("Previous report loaded successfully.");
    } catch (err) {
        console.error("Error loading previous report:", err);
        alert("Error loading report: " + err.message);
    }
}

document.addEventListener('DOMContentLoaded', function () {
    // Basic element check for chat container
    const chatContainer = document.getElementById('chat-container');
    if (!chatContainer) {
        console.error("Error: Element with id 'chat-container' not found.");
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

    // ----- Prompt Set Dropdown -----
    const promptSelector = document.getElementById('prompt-set-selector');
    async function loadPromptSets() {
        try {
            const response = await fetch("/reportComposerAPI/get_prompts");
            if (!response.ok) throw new Error("Failed to fetch prompts");
            const promptFiles = await response.json();
            promptSelector.innerHTML = "";
            promptFiles.forEach(file => {
                const fileName = file.replace(/^.*[\\/]/, '').replace(/\.[^/.]+$/, "");
                const option = document.createElement("option");
                option.value = file;
                option.textContent = fileName;
                promptSelector.appendChild(option);
            });
        } catch (error) {
            console.error("Error loading prompt sets:", error);
            promptSelector.innerHTML = "<option>Error loading prompts</option>";
        }
    }
    loadPromptSets();

    promptSelector.addEventListener('change', async function () {
        const selectedPrompt = this.value;
        if (!selectedPrompt) return;
        try {
            const updateResponse = await fetch("/reportComposerAPI/update_prompt", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ yaml_file_path: selectedPrompt }),
            });
            if (!updateResponse.ok) throw new Error("Failed to update prompt");
            console.log("Prompt updated to:", selectedPrompt);
        } catch (error) {
            console.error("Error updating prompt set:", error);
        }
    });

    // ----- D3.js Initialization for DAG -----
    svg = d3.select("#dag-svg")
        .attr("viewBox", "-500 -500 1000 1000")
        .attr("preserveAspectRatio", "xMidYMid meet");
    g = svg.append("g");

    zoom = d3.zoom()
        .scaleExtent([0.5, 3])
        .on("zoom", function (event) {
            g.attr("transform", event.transform);
        });

    // ----- Initiate Report Generation -----
    window.initiateReport = async function () {
        const input = document.getElementById('chat-input');
        const companyName = input.value.trim();
        if (!companyName) return;
        if (!chatContainer) {
            console.error("Cannot find 'chat-container'.");
            return;
        }
        const selectedPrompt = promptSelector.value;
        if (!selectedPrompt) {
            console.error("No prompt set selected.");
            return;
        }
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
                    mock: window.mock_global,
                    prompt_name: selectedPrompt,
                    web_search: window.web_search_enabled
                })
            });
            if (!response.ok) throw new Error("Request failed with status " + response.status);
            const data = await response.json();
            const taskId = data.task_id;
            window.currentTaskId = taskId;
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

    // ----- Top Menu Bar "Load Previous Report" Input Handler -----
    // Assuming the top menu bar has a button with id "load-report-btn" in the header.
    // We attach a click handler to that button to toggle a small input field.
    const topLoadBtn = document.getElementById("load-report-btn");
    topLoadBtn.addEventListener("click", function () {
        // Toggle display of an input field (or you could create a modal)
        let loadContainer = document.getElementById("top-load-container");
        if (!loadContainer) {
            loadContainer = document.createElement("div");
            loadContainer.id = "top-load-container";
            loadContainer.className = "mt-2 flex items-center space-x-2";
            const taskIdInput = document.createElement("input");
            taskIdInput.id = "top-task-id-input";
            taskIdInput.type = "text";
            taskIdInput.placeholder = "Enter Task ID...";
            taskIdInput.className = "border rounded p-2";
            const topLoadSubmit = document.createElement("button");
            topLoadSubmit.innerText = "Load";
            topLoadSubmit.className = "bg-green-500 hover:bg-green-600 text-white p-2 rounded";
            topLoadSubmit.addEventListener("click", function () {
                loadPreviousReport(taskIdInput.value);
            });
            loadContainer.appendChild(taskIdInput);
            loadContainer.appendChild(topLoadSubmit);
            // Append the container into the header (next to the Load Previous Report button)
            const header = document.querySelector("header");
            header.appendChild(loadContainer);
        } else {
            // If already visible, you may choose to hide it
            loadContainer.style.display = loadContainer.style.display === "none" ? "flex" : "none";
        }
    });

    // ----- Auto-Center Button -----
    const centerBtn = document.createElement("button");
    centerBtn.innerText = "Auto-Center";
    centerBtn.className = "p-2 bg-blue-500 text-white rounded";
    centerBtn.onclick = autoCenterGraph;
    document.getElementById("dag-updates-container").prepend(centerBtn);
});

// =============================
// PART 2 OF 2
// =============================

// --- initGraph and D3 Helpers ---
function initGraph(dagData) {
    console.log("initGraph called with DAG data:", dagData);
    nodes = dagData.nodes;
    links = dagData.links;
    // Clear previous graph elements
    g.selectAll("*").remove();

    simulation = d3.forceSimulation(nodes)
        .force("link", d3.forceLink(links).id(d => d.id).distance(120))
        .force("charge", d3.forceManyBody().strength(-300))
        .force("center", d3.forceCenter(0, 0))
        .force("collide", d3.forceCollide().radius(30));

    linkSelection = g.append("g")
        .attr("class", "links")
        .selectAll("line")
        .data(links)
        .enter().append("line")
        .attr("stroke", "#999")
        .attr("stroke-width", 2);

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
            const details = nodeDetails[d.id];
            if (details) displayNodeDetails(d.id, details);
        });

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

    simulation.on("end", () => {
        console.log("Graph simulation stabilized. Auto-centering...");
        autoCenterGraph();
    });

    svg.call(d3.zoom()
        .scaleExtent([0.5, 3])
        .on("zoom", function(event) {
            g.attr("transform", event.transform);
        }));
}

function autoCenterGraph() {
    if (!nodes.length) return;
    const minX = d3.min(nodes, d => d.x);
    const maxX = d3.max(nodes, d => d.x);
    const minY = d3.min(nodes, d => d.y);
    const maxY = d3.max(nodes, d => d.y);
    const graphWidth = maxX - minX;
    const graphHeight = maxY - minY;
    const centerX = minX + graphWidth / 1;
    const centerY = minY + graphHeight / 1;
    const scale = Math.min(
        width / (graphWidth * 2),
        height / (graphHeight * 2)
    );
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

// Drag Handlers
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

// --- WebSocket Handling ---
function openWebSocketForTask(taskId) {
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${window.location.host}/reportComposerAPI/ws/${taskId}`;
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => console.log("WebSocket connected for task ID:", taskId);
    ws.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.type === "init") {
            initGraph(message.dag);
        } else if (message.type === "update") {
            updateNodeStatus(message.node_id, message.status, message.result);
            nodeDetails[message.node_id] = {
                status: message.status,
                result: message.result
            };
            checkIfAllNodesComplete();
        }
    };
    ws.onclose = () => console.log("WebSocket closed for task:", taskId);
    ws.onerror = err => console.error("WebSocket error:", err);
}

function updateNodeStatus(nodeId, status, result) {
    const node = nodes.find(n => n.id == nodeId);
    if (!node) return;
    let newColor = "#ccc";
    if (status === "processing") {
        newColor = "#FFD700";
        svg.selectAll("circle")
            .filter(d => d.id == nodeId)
            .classed("breathing", true);
    } else if (status === "complete") {
        newColor = "#32CD32";
        svg.selectAll("circle")
            .filter(d => d.id == nodeId)
            .classed("breathing", false);
    } else if (status === "failed") {
        newColor = "#FF4500";
        svg.selectAll("circle")
            .filter(d => d.id == nodeId)
            .classed("breathing", false);
    }
    svg.selectAll("circle")
        .filter(d => d.id == nodeId)
        .transition().duration(500)
        .attr("fill", newColor);
}

// --- Node Details Display ---
function displayNodeDetails(nodeId, details) {
    const chatHistory = document.getElementById("node-view");
    chatHistory.innerHTML = "";
    const nodeHeader = document.createElement("h3");
    nodeHeader.className = "text-base font-semibold mb-1";
    nodeHeader.innerText = `Node ${nodeId}`;
    const statusPara = document.createElement("p");
    statusPara.className = "text-sm text-gray-300 mb-3";
    statusPara.innerText = `Status: ${details.status}`;
    let resultObj = details.result;
    if (typeof resultObj === "string") {
        try {
            resultObj = JSON.parse(resultObj);
        } catch (err) {
            console.warn("Result is not valid JSON, using raw string.");
        }
    }
    resultObj = resultObj || {};
    const sectionTitle = resultObj.section_title || resultObj.section_tile || "Untitled Section";
    let llmResponse = resultObj.llm || "No LLM response found.";
    const sectionTitleEl = document.createElement("h2");
    sectionTitleEl.className = "text-lg font-bold mb-2";
    sectionTitleEl.innerText = sectionTitle;
    const llmDiv = document.createElement("div");
    llmDiv.className = "whitespace-pre-wrap mb-4";
    let finalMarkdown = llmResponse;
    if (typeof llmResponse !== "string") {
        finalMarkdown = JSON.stringify(llmResponse, null, 2);
    }
    const renderer = new marked.Renderer();
    renderer.heading = function (text, level) {
        const headingText = (typeof text === "object") ? text.text : text;
        level = Math.max(level || 3, 3);
        return `<h${level}>${headingText}</h${level}>`;
    };
    llmDiv.innerHTML = marked.parse(finalMarkdown, { renderer });
    // Online Data
    const onlineDataDiv = document.createElement("div");
    onlineDataDiv.className = "text-sm text-gray-300 whitespace-pre-wrap text-left";
    const onlineData = resultObj.online_data || "No online data found.";
    let onlineDataContent = "";
    if (Array.isArray(onlineData.results)) {
        onlineData.results.forEach((resObj) => {
            for (const [title, content] of Object.entries(resObj)) {
                onlineDataContent += `<p class="text-left mb-2">
                    <strong>${title}:</strong><br>
                    ${typeof content === 'object' ? JSON.stringify(content, null, 2).trim() : content.trim()}
                </p><hr class="my-2 border-gray-500" />`;
            }
        });
    } else {
        onlineDataContent = (typeof onlineData === "object")
            ? JSON.stringify(onlineData, null, 2)
            : String(onlineData);
    }
    onlineDataDiv.innerHTML = onlineDataContent;
    const separator0 = document.createElement("hr");
    const separator1 = document.createElement("hr");
    const separator2 = document.createElement("hr");
    separator1.className = "my-2 border-gray-500";
    separator2.className = "my-2 border-gray-500";
    const onlineDataHeader = document.createElement("h3");
    onlineDataHeader.className = "text-lg font-bold mb-2 mt-4";
    onlineDataHeader.innerText = "Online Data";
    chatHistory.appendChild(separator0);
    chatHistory.appendChild(nodeHeader);
    chatHistory.appendChild(statusPara);
    chatHistory.appendChild(sectionTitleEl);
    chatHistory.appendChild(separator1);
    chatHistory.appendChild(llmDiv);
    chatHistory.appendChild(separator2);
    chatHistory.appendChild(onlineDataHeader);
    chatHistory.appendChild(onlineDataDiv);
}

// --- Task Save and Load Helpers ---
function checkIfAllNodesComplete() {
    if (!nodes || !nodes.length) {
        console.log("No nodes available to check.");
        return false;
    }
    const allComplete = nodes.every(n => {
        const nodeId = n.id.toString();
        const nodeStatus = nodeDetails[nodeId]?.status || "undefined";
        console.log(`Node ${nodeId} status: ${nodeStatus}`);
        return nodeDetails[nodeId] && nodeDetails[nodeId].status === "complete";
    });
    console.log("All nodes complete?", allComplete);
    if (allComplete) {
        showSaveTaskButton();
    }
    return allComplete;
}

function showSaveTaskButton() {
    if (document.getElementById("save-task-button")) return;
    const saveBtn = document.createElement("button");
    saveBtn.id = "save-task-button";
    saveBtn.innerText = "Save Task";
    saveBtn.className = "p-2 bg-green-500 text-white rounded ml-2";
    saveBtn.onclick = saveTask;
    const container = document.getElementById("dag-updates-container");
    container.appendChild(saveBtn);
}

async function saveTask() {
    try {
        const taskId = window.currentTaskId;
        if (!taskId) {
            console.error("No currentTaskId found, cannot save.");
            return;
        }
        const response = await fetch(`/reportComposerAPI/save_task_result/${taskId}`, {
            method: "POST"
        });
        if (!response.ok) {
            throw new Error(`Save failed: HTTP ${response.status}`);
        }
        const saveBtn = document.getElementById("save-task-button");
        if (saveBtn) saveBtn.remove();
        createTaskIdButton(taskId);
        console.log("Task saved successfully. Task ID:", taskId);
    } catch (err) {
        console.error("Error saving task:", err);
    }
}

function createTaskIdButton(taskId) {
    const taskIdBtn = document.createElement("button");
    taskIdBtn.innerText = `Task ID: ${taskId}`;
    taskIdBtn.className = "p-2 bg-blue-500 text-white rounded ml-2";
    taskIdBtn.onclick = () => {
        navigator.clipboard.writeText(taskId)
            .then(() => console.log(`Task ID ${taskId} copied to clipboard`))
            .catch(err => console.error("Failed to copy Task ID:", err));
    };
    const container = document.getElementById("dag-updates-container");
    container.appendChild(taskIdBtn);
}

// --- Additional UI Toggles ---
window.toggleChatHistory = function () {
    const sidebar = document.getElementById('sidebar');
    const toggleButton = document.getElementById('toggle-sidebar-btn');
    sidebar.classList.toggle('hidden');
    if (sidebar.classList.contains('hidden')) {
        toggleButton.innerText = "📂 Open Node View";
    } else {
        toggleButton.innerText = "📂 Hide Node View";
    }
};

window.toggleMock = function () {
    window.mock_global = !window.mock_global;
    const btn = document.getElementById("toggle-mock-button");
    btn.innerText = "Mock: " + (window.mock_global ? "ON" : "OFF");
    console.log("mock_global toggled: " + window.mock_global);
};

function toggleWebSearch() {
    window.web_search_enabled = !window.web_search_enabled;
    const btn = document.getElementById('toggle-websearch-btn');
    if (btn) {
        btn.innerText = window.web_search_enabled ? "ON 🌐" : "OFF ⭕️";
    }
    console.log("Web search toggled: " + window.web_search_enabled);
}

// Create the toggle button for mock mode once the DOM is loaded
document.addEventListener('DOMContentLoaded', function () {
    const toggleMockButton = document.createElement("button");
    toggleMockButton.id = "toggle-mock-button";
    toggleMockButton.innerText = "Mock: OFF";
    toggleMockButton.className = "p-2 bg-green-500 text-white rounded m-2";
    const userInfoDiv = document.querySelector('.user-info');
    if (userInfoDiv) {
        userInfoDiv.appendChild(toggleMockButton);
    } else {
        document.body.appendChild(toggleMockButton);
    }
    toggleMockButton.addEventListener('click', window.toggleMock);
});

