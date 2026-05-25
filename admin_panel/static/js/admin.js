// ANPR Admin Panel - JavaScript Functions

// Global variables
let refreshInterval;
let lastDetectionTimestamp = null; // Track last detection to avoid duplicate notifications
let pageLoadTime = Date.now(); // Track when page was loaded
let initialLoadComplete = false; // Flag to suppress notifications during initial page load

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeAdminPanel();
    initializeSecurity();
    initializeNetworkMonitoring();
});

// WebSocket connection for real-time updates
let socket = null;
let reconnectAttempts = 0;
const maxReconnectAttempts = 10;
let reconnectTimeout = null;
let connectionStatus = 'disconnected'; // 'connected', 'connecting', 'disconnected', 'error'
let lastConnectionTime = null;
let connectionHealthCheck = null;

// Initialize WebSocket connection
function initializeWebSocket() {
    try {
        // Check if Socket.IO is available
        if (typeof io === 'undefined') {
            console.warn('Socket.IO not loaded, real-time features disabled');
            updateConnectionStatus('error', 'Socket.IO not available');
            showNotification('Real-time features disabled - Socket.IO not available', 'warning');
            return;
        }
        
        // Clear any existing reconnection timeout
        if (reconnectTimeout) {
            clearTimeout(reconnectTimeout);
            reconnectTimeout = null;
        }
        
        // Update connection status
        updateConnectionStatus('connecting', 'Connecting...');
        
        // Connect to WebSocket server with optimized settings
        socket = io({
            transports: ['websocket'],
            upgrade: false,
            rememberUpgrade: false,
            timeout: 10000, // Increased timeout for better reliability
            forceNew: true,
            reconnection: false, // We'll handle reconnection manually
            autoConnect: true
        });
        
        // Connection event handlers
        socket.on('connect', function() {
            console.log('✅ Connected to ANPR Admin Panel WebSocket');
            reconnectAttempts = 0;
            lastConnectionTime = Date.now();
            updateConnectionStatus('connected', 'Connected');
            
            // Start health check
            startConnectionHealthCheck();
            
            // Join appropriate rooms based on current page
            const currentPage = getCurrentPage();
            if (currentPage) {
                socket.emit('join_room', { room: currentPage });
            }
            
            // Show connection success only if it was a reconnection
            if (reconnectAttempts > 0) {
                showNotification('Connection restored!', 'success');
            }
        });
        
        socket.on('disconnect', function(reason) {
            console.log('❌ Disconnected from ANPR Admin Panel WebSocket. Reason:', reason);
            updateConnectionStatus('disconnected', 'Disconnected');
            
            // Stop health check
            stopConnectionHealthCheck();
            
            // Only show disconnect notification if it was an unexpected disconnect
            if (reason !== 'io client disconnect' && reconnectAttempts === 0) {
                showNotification('Connection lost. Attempting to reconnect...', 'warning');
            }
            
            // Attempt reconnection unless it was a manual disconnect
            if (reason !== 'io client disconnect') {
                attemptReconnect();
            }
        });
        
        socket.on('connect_error', function(error) {
            console.error('WebSocket connection error:', error);
            updateConnectionStatus('error', 'Connection failed');
            attemptReconnect();
        });
        
        socket.on('reconnect', function(attemptNumber) {
            console.log('🔄 Reconnected after', attemptNumber, 'attempts');
            updateConnectionStatus('connected', 'Reconnected');
            showNotification('Connection restored!', 'success');
        });
        
        socket.on('reconnect_attempt', function(attemptNumber) {
            console.log('🔄 Reconnection attempt', attemptNumber);
            updateConnectionStatus('connecting', `Reconnecting... (${attemptNumber})`);
        });
        
        socket.on('reconnect_error', function(error) {
            console.error('Reconnection error:', error);
            updateConnectionStatus('error', 'Reconnection failed');
        });
        
        socket.on('reconnect_failed', function() {
            console.error('❌ All reconnection attempts failed');
            updateConnectionStatus('error', 'Connection failed');
            showNotification('Unable to reconnect. Please refresh the page.', 'error');
        });
        
        socket.on('pong', function(data) {
            // Health check response received
            if (data.error) {
                console.warn('Health check error:', data.error);
            } else {
                console.log('🏓 Pong received:', data);
            }
        });
        
        // Real-time update handlers
        socket.on('new_detections', function(data) {
            updateDetectionFeed(data);
        });
        
        socket.on('detection_update', function(data) {
            updateDetectionStats(data);
        });
        
        socket.on('system_status', function(data) {
            updateSystemStatus(data);
        });
        
        socket.on('camera_status', function(data) {
            updateCameraStatus(data);
        });
        
        // Camera control handlers
        socket.on('camera_toggle_result', function(data) {
            handleCameraToggleResult(data);
        });
        
        socket.on('camera_test_result', function(data) {
            handleCameraTestResult(data);
        });
        
        socket.on('cameras_refreshed', function(data) {
            handleCamerasRefreshed(data);
        });
        
        socket.on('connected', function(data) {
            console.log('WebSocket:', data.message);
        });
        
        // Request initial updates
        socket.emit('request_update', { type: 'all' });
        
    } catch (error) {
        console.error('Error initializing WebSocket:', error);
    }
}

// Get current page for room joining
function getCurrentPage() {
    const path = window.location.pathname;
    if (path.includes('/dashboard')) return 'dashboard';
    if (path.includes('/detections')) return 'detections';
    if (path.includes('/cameras')) return 'cameras';
    if (path.includes('/plates')) return 'plates';
    return 'dashboard';
}

// Attempt to reconnect WebSocket
function attemptReconnect() {
    if (reconnectAttempts < maxReconnectAttempts) {
        reconnectAttempts++;
        console.log(`Attempting to reconnect... (${reconnectAttempts}/${maxReconnectAttempts})`);
        
        // Calculate exponential backoff with jitter
        const baseDelay = 1000; // 1 second base
        const maxDelay = 30000; // 30 seconds max
        const delay = Math.min(baseDelay * Math.pow(2, reconnectAttempts - 1), maxDelay);
        const jitter = Math.random() * 1000; // Add up to 1 second of jitter
        const totalDelay = delay + jitter;
        
        updateConnectionStatus('connecting', `Reconnecting in ${Math.round(totalDelay/1000)}s...`);
        
        reconnectTimeout = setTimeout(() => {
            if (socket && socket.disconnected) {
                console.log('Attempting to reconnect socket...');
                socket.connect();
            } else if (!socket) {
                console.log('Reinitializing WebSocket...');
                initializeWebSocket();
            }
        }, totalDelay);
    } else {
        console.error('Max reconnection attempts reached');
        updateConnectionStatus('error', 'Connection failed');
        showNotification('Unable to reconnect. Please refresh the page.', 'error');
    }
}

// Update connection status indicator
function updateConnectionStatus(status, message) {
    connectionStatus = status;
    
    // Update connection indicator in UI
    const statusIndicator = document.getElementById('connection-status');
    if (statusIndicator) {
        statusIndicator.className = `connection-status ${status}`;
        statusIndicator.textContent = message;
    }
    
    // Update page title with connection status
    const originalTitle = document.title.replace(/^\[.*?\] /, '');
    if (status === 'connected') {
        document.title = originalTitle;
    } else if (status === 'connecting') {
        document.title = `[Connecting...] ${originalTitle}`;
    } else if (status === 'disconnected') {
        document.title = `[Disconnected] ${originalTitle}`;
    } else if (status === 'error') {
        document.title = `[Connection Error] ${originalTitle}`;
    }
}

// Start connection health check
function startConnectionHealthCheck() {
    stopConnectionHealthCheck(); // Clear any existing health check
    
    connectionHealthCheck = setInterval(() => {
        if (socket && socket.connected) {
            // Send ping to check connection health
            socket.emit('ping', { timestamp: Date.now() });
        } else {
            console.warn('Health check: Socket not connected');
            updateConnectionStatus('disconnected', 'Connection lost');
            attemptReconnect();
        }
    }, 30000); // Check every 30 seconds
}

// Handle network status changes
function handleNetworkStatusChange() {
    if (navigator.onLine) {
        console.log('🌐 Network is online');
        if (connectionStatus === 'error' || connectionStatus === 'disconnected') {
            console.log('Attempting to reconnect due to network restoration');
            manualReconnect();
        }
    } else {
        console.log('🌐 Network is offline');
        updateConnectionStatus('error', 'Network offline');
        showNotification('Network connection lost', 'warning');
    }
}

// Initialize network status monitoring
function initializeNetworkMonitoring() {
    window.addEventListener('online', handleNetworkStatusChange);
    window.addEventListener('offline', handleNetworkStatusChange);
}

// Cleanup function for page unload
function cleanup() {
    console.log('🧹 Cleaning up WebSocket connection...');
    
    // Stop health check
    stopConnectionHealthCheck();
    
    // Clear reconnection timeout
    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
    }
    
    // Disconnect socket
    if (socket) {
        socket.disconnect();
        socket = null;
    }
    
    // Remove event listeners
    window.removeEventListener('online', handleNetworkStatusChange);
    window.removeEventListener('offline', handleNetworkStatusChange);
}

// Handle page unload
window.addEventListener('beforeunload', cleanup);
window.addEventListener('unload', cleanup);

// Stop connection health check
function stopConnectionHealthCheck() {
    if (connectionHealthCheck) {
        clearInterval(connectionHealthCheck);
        connectionHealthCheck = null;
    }
}

// Manual reconnection function
function manualReconnect() {
    console.log('Manual reconnection requested');
    reconnectAttempts = 0; // Reset attempts for manual reconnect
    
    if (socket) {
        socket.disconnect();
        socket.connect();
    } else {
        initializeWebSocket();
    }
}

// Get connection status
function getConnectionStatus() {
    return {
        status: connectionStatus,
        connected: socket ? socket.connected : false,
        reconnectAttempts: reconnectAttempts,
        lastConnectionTime: lastConnectionTime
    };
}

// Update detection feed with new detections
function updateDetectionFeed(data) {
    console.log('New detections:', data);
    
    // Update detection count in dashboard
    const detectionCountElement = document.getElementById('totalDetections');
    if (detectionCountElement) {
        detectionCountElement.textContent = data.count;
        detectionCountElement.classList.add('updated');
        setTimeout(() => detectionCountElement.classList.remove('updated'), 300);
    }
    
        // Add to activity feed for new detections
        if (data.detections && data.detections.length > 0) {
            const latestDetection = data.detections[0];
            console.log('Latest detection data:', latestDetection);
            
            // Get detection timestamp (could be in different formats)
            let detectionTime = null;
            if (latestDetection.timestamp) {
                detectionTime = new Date(latestDetection.timestamp).getTime();
            } else if (latestDetection.time) {
                detectionTime = new Date(latestDetection.time).getTime();
            }
            
            // Only show notification if:
            // 1. Initial page load is complete (don't show notifications for data loaded on page load)
            // 2. It's a verified plate
            // 3. It's actually a new detection (happened after page load or after last known detection)
            const isNewDetection = detectionTime && (
                detectionTime > pageLoadTime || 
                (lastDetectionTimestamp && detectionTime > lastDetectionTimestamp)
            );
            
            // Only show notification for truly new, verified detections (after initial load)
            if (initialLoadComplete && latestDetection.verification_status === 'VERIFIED' && latestDetection.plate && isNewDetection) {
                showNotification(`Verified plate detected: ${latestDetection.plate}`, 'success');
                // Update last detection timestamp
                if (detectionTime) {
                    lastDetectionTimestamp = detectionTime;
                }
            }
            
            // Update last detection timestamp even if we don't show notification
            if (detectionTime && (!lastDetectionTimestamp || detectionTime > lastDetectionTimestamp)) {
                lastDetectionTimestamp = detectionTime;
            }
            
            // Add to activity feed (but only for new detections)
            if (isNewDetection) {
                addActivityItem('New Detection', `Plate ${latestDetection.plate || 'Unknown'} detected by ${latestDetection.camera_name || latestDetection.camera || 'Unknown Camera'}`, 'camera-video', 'success');
            }
        }
}

// Update detection statistics
function updateDetectionStats(data) {
    console.log('Detection stats update:', data);
    
    // Update stats cards
    const totalDetectionsElement = document.getElementById('total-detections');
    if (totalDetectionsElement) {
        totalDetectionsElement.textContent = data.total_detections || 0;
        totalDetectionsElement.style.color = ''; // Reset color
    }
    
    const verifiedDetectionsElement = document.getElementById('verified-detections');
    if (verifiedDetectionsElement) {
        verifiedDetectionsElement.textContent = data.verified_detections || 0;
        verifiedDetectionsElement.style.color = ''; // Reset color
    }
    
    const notVerifiedDetectionsElement = document.getElementById('unverified-detections');
    if (notVerifiedDetectionsElement) {
        notVerifiedDetectionsElement.textContent = data.not_verified_detections || 0;
        notVerifiedDetectionsElement.style.color = ''; // Reset color
    }
    
    const todayDetectionsElement = document.getElementById('today-detections');
    if (todayDetectionsElement) {
        todayDetectionsElement.textContent = data.detections_today || 0;
        todayDetectionsElement.style.color = ''; // Reset color
    }
    
    // Show live update indicator
    showLiveUpdateIndicator();
}

// Update system status
function updateSystemStatus(data) {
    console.log('System status update:', data);
    
    // Handle nested structure (data.anpr_service.running vs data.anpr_running)
    const isRunning = data.anpr_running !== undefined ? data.anpr_running : 
                     (data.anpr_service && data.anpr_service.running !== undefined ? data.anpr_service.running : false);
    
    // Update system status indicators
    const systemStatusElement = document.getElementById('systemStatus');
    if (systemStatusElement) {
        const statusClass = isRunning ? 'text-success' : 'text-danger';
        const statusText = isRunning ? 'Online' : 'Offline';
        systemStatusElement.className = `badge badge-modern bg-${isRunning ? 'success' : 'danger'}-gradient me-2`;
        systemStatusElement.textContent = statusText;
    }
    
    // Update ANPR service status
    const anprServiceElement = document.getElementById('anprServiceStatus');
    if (anprServiceElement) {
        const iconClass = isRunning ? 'text-success' : 'text-danger';
        const statusText = isRunning ? 'Running' : 'Stopped';
        anprServiceElement.innerHTML = `<i class="bi bi-circle-fill ${iconClass} me-1"></i><span>${statusText}</span>`;
        anprServiceElement.classList.add('updated');
        setTimeout(() => anprServiceElement.classList.remove('updated'), 300);
    }
    
    // Update last detection time
    if (data.last_detection) {
        const lastDetectionElement = document.getElementById('lastDetection');
        if (lastDetectionElement) {
            lastDetectionElement.innerHTML = `<i class="bi bi-clock me-1"></i><span>${formatTimestamp(data.last_detection)}</span>`;
            lastDetectionElement.classList.add('updated');
            setTimeout(() => lastDetectionElement.classList.remove('updated'), 300);
        }
    }
    
    // Update active cameras count
    if (data.active_cameras !== undefined || data.enabled_cameras !== undefined) {
        const activeCamerasElement = document.getElementById('activeCameras');
        if (activeCamerasElement) {
            const activeCount = data.active_cameras || data.enabled_cameras || 0;
            const totalCount = data.total_cameras || 0;
            activeCamerasElement.innerHTML = `<i class="bi bi-camera me-1"></i><span>${activeCount}/${totalCount}</span>`;
            activeCamerasElement.classList.add('updated');
            setTimeout(() => activeCamerasElement.classList.remove('updated'), 300);
        }
    }
    
    // Update system uptime
    let uptimeSeconds = null;
    if (data.uptime !== undefined) {
        uptimeSeconds = data.uptime;
    } else if (data.anpr_service && data.anpr_service.uptime !== undefined) {
        uptimeSeconds = data.anpr_service.uptime;
    }
    
    if (uptimeSeconds !== null) {
        const systemUptimeElement = document.getElementById('systemUptime');
        if (systemUptimeElement) {
            const hours = Math.floor(uptimeSeconds / 3600);
            const minutes = Math.floor((uptimeSeconds % 3600) / 60);
            const seconds = Math.floor(uptimeSeconds % 60);
            let uptimeText = '';
            if (hours > 0) {
                uptimeText = `${hours}h ${minutes}m`;
            } else if (minutes > 0) {
                uptimeText = `${minutes}m ${seconds}s`;
            } else {
                uptimeText = `${seconds}s`;
            }
            systemUptimeElement.innerHTML = `<i class="bi bi-stopwatch me-1"></i><span>${uptimeText}</span>`;
            systemUptimeElement.classList.add('updated');
            setTimeout(() => systemUptimeElement.classList.remove('updated'), 300);
        }
    } else {
        // If uptime not available, show "N/A" or keep calculating
        const systemUptimeElement = document.getElementById('systemUptime');
        if (systemUptimeElement && systemUptimeElement.textContent.includes('Calculating')) {
            // Keep "Calculating..." if service is not running
            if (!data.anpr_running) {
                systemUptimeElement.innerHTML = `<i class="bi bi-stopwatch me-1"></i><span>N/A</span>`;
            }
        }
    }
    
    // Show live indicator
    showLiveUpdateIndicator();
}

// Update camera status
function updateCameraStatus(data) {
    console.log('Camera status update:', data);
    
    // Update active cameras in system status section
    const activeCamerasElement = document.getElementById('activeCameras');
    if (activeCamerasElement) {
        const enabledCount = data.enabled_cameras || (data.cameras ? data.cameras.filter(c => c.enabled).length : 0);
        const totalCount = data.total_cameras || (data.cameras ? data.cameras.length : 0);
        activeCamerasElement.innerHTML = `<i class="bi bi-camera me-1"></i><span>${enabledCount}/${totalCount}</span>`;
        activeCamerasElement.classList.add('updated');
        setTimeout(() => activeCamerasElement.classList.remove('updated'), 300);
    }
    
    // Update camera count with enhanced stats
    const cameraStatusCountElement = document.getElementById('cameraStatusCount');
    if (cameraStatusCountElement) {
        const enabledCount = data.enabled_cameras || (data.cameras ? data.cameras.filter(c => c.enabled).length : 0);
        const activeCount = data.active_cameras || (data.cameras ? data.cameras.filter(c => c.connection_status === 'connected').length : 0);
        const totalCount = data.total_cameras || (data.cameras ? data.cameras.length : 0);
        cameraStatusCountElement.textContent = `${enabledCount}/${totalCount} Enabled | ${activeCount} Connected`;
    }
    
    // Update camera status indicators with enhanced information
    data.cameras.forEach(camera => {
        const cameraElement = document.querySelector(`[data-camera-id="${camera.id}"]`);
        if (cameraElement) {
            // Update status badge with connection status
            const statusBadge = cameraElement.querySelector('.camera-status-badge');
            if (statusBadge) {
                const connectionStatus = camera.connection_status || 'unknown';
                const quality = camera.connection_quality || 'unknown';
                
                let badgeClass, badgeText;
                if (connectionStatus === 'connected') {
                    badgeClass = `badge badge-modern bg-${camera.enabled ? 'success' : 'warning'}-gradient`;
                    badgeText = camera.enabled ? `Active (${quality})` : `Connected (${quality})`;
                } else if (connectionStatus === 'disconnected') {
                    badgeClass = 'badge badge-modern bg-danger-gradient';
                    badgeText = 'Disconnected';
                } else if (connectionStatus === 'timeout') {
                    badgeClass = 'badge badge-modern bg-warning-gradient';
                    badgeText = 'Timeout';
                } else {
                    badgeClass = 'badge badge-modern bg-secondary-gradient';
                    badgeText = 'Unknown';
                }
                
                statusBadge.className = badgeClass;
                statusBadge.textContent = badgeText;
            }
            
            // Update status indicator dot with connection quality
            const statusIndicator = cameraElement.querySelector('.camera-status-indicator');
            if (statusIndicator) {
                const connectionStatus = camera.connection_status || 'unknown';
                const quality = camera.connection_quality || 'unknown';
                
                let indicatorClass = 'camera-status-indicator';
                if (connectionStatus === 'connected') {
                    indicatorClass += ` active quality-${quality}`;
                } else if (connectionStatus === 'disconnected') {
                    indicatorClass += ' disconnected';
                } else if (connectionStatus === 'timeout') {
                    indicatorClass += ' timeout';
                } else {
                    indicatorClass += ' unknown';
                }
                
                statusIndicator.className = indicatorClass;
                
                // Add tooltip with connection details
                const responseTime = camera.response_time || 0;
                const errorMessage = camera.error_message || '';
                statusIndicator.title = `Status: ${connectionStatus}\nQuality: ${quality}\nResponse: ${responseTime}ms${errorMessage ? `\nError: ${errorMessage}` : ''}`;
            }
            
            // Update last checked time
            const lastCheckedElement = cameraElement.querySelector('.camera-last-checked');
            if (lastCheckedElement && camera.last_checked) {
                lastCheckedElement.textContent = `Last checked: ${formatTimestamp(camera.last_checked)}`;
            }
        }
    });
    
    // Don't add to activity feed to reduce spam
}

// Camera control handler functions
function handleCameraToggleResult(data) {
    const cameraElement = document.querySelector(`[data-camera-id="${data.camera_id}"]`);
    const toggleButton = cameraElement?.querySelector('button[onclick*="toggleCameraLive"]');
    
    if (data.success) {
        // UI already updated, restore button state
        if (toggleButton) {
            const buttonText = data.enabled ? 'Disable' : 'Enable';
            const iconClass = data.enabled ? 'bi-pause' : 'bi-play';
            toggleButton.innerHTML = `<i class="bi ${iconClass} me-1"></i>${buttonText}`;
            toggleButton.disabled = false;
            toggleButton.classList.remove('processing');
        }
        if (cameraElement) {
            cameraElement.classList.remove('processing');
        }
        showNotification(data.message, 'success');
        addActivityItem('Camera Control', data.message, 'camera-video', 'success');
        
        // Refresh page data immediately after successful operation
        refreshPageData();
        
        // Force page reload after 1.5 seconds to ensure data is updated
        setTimeout(() => {
            location.reload();
        }, 1500);
    } else {
        // Revert UI changes on failure
        if (cameraElement) {
            const currentEnabled = data.enabled;
            updateCameraUI(data.camera_id, !currentEnabled);
            if (toggleButton) {
                const buttonText = !currentEnabled ? 'Disable' : 'Enable';
                const iconClass = !currentEnabled ? 'bi-pause' : 'bi-play';
                toggleButton.innerHTML = `<i class="bi ${iconClass} me-1"></i>${buttonText}`;
                toggleButton.disabled = false;
                toggleButton.classList.remove('processing');
            }
            cameraElement.classList.remove('processing');
        }
        showNotification(data.error || 'Failed to toggle camera', 'error');
        addActivityItem('Camera Control', data.error || 'Failed to toggle camera', 'camera-video', 'error');
    }
}

function handleCameraTestResult(data) {
    if (data.success) {
        showNotification(data.message, 'success');
        addActivityItem('Camera Test', data.message, 'wifi', 'success');
        
        // Refresh page data immediately after successful test
        refreshPageData();
        
        // Force page reload after 1.5 seconds to ensure data is updated
        setTimeout(() => {
            location.reload();
        }, 1500);
    } else {
        showNotification(data.message || 'Camera test failed', 'error');
        addActivityItem('Camera Test', data.message || 'Camera test failed', 'wifi', 'error');
    }
}

function handleCamerasRefreshed(data) {
    if (data.success) {
        showNotification(data.message, 'info');
    } else {
        showNotification(data.error || 'Failed to refresh cameras', 'error');
    }
}

// Live camera control functions
function toggleCameraLive(cameraId, enabled) {
    const cameraElement = document.querySelector(`[data-camera-id="${cameraId}"]`);
    const toggleButton = cameraElement?.querySelector('button[onclick*="toggleCameraLive"]');
    
    // Prevent spam clicking
    if (toggleButton && toggleButton.disabled) {
        return;
    }
    
    // Show immediate progress feedback
    if (toggleButton) {
        const originalText = toggleButton.innerHTML;
        toggleButton.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Processing...';
        toggleButton.disabled = true;
        toggleButton.classList.add('processing');
    }
    
    // Add visual feedback to camera card
    if (cameraElement) {
        cameraElement.classList.add('processing');
    }
    
    // Immediately update UI for better responsiveness
    updateCameraUI(cameraId, enabled);
    
    // Show immediate success notification
    showNotification(`Camera ${enabled ? 'enabled' : 'disabled'} successfully`, 'success');
    
    if (socket && socket.connected) {
        socket.emit('camera_toggle', {
            camera_id: cameraId,
            enabled: enabled
        });
        
        // Fallback timeout in case response is too slow
        setTimeout(() => {
            if (toggleButton && toggleButton.disabled) {
                const buttonText = enabled ? 'Disable' : 'Enable';
                const iconClass = enabled ? 'bi-pause' : 'bi-play';
                toggleButton.innerHTML = `<i class="bi ${iconClass} me-1"></i>${buttonText}`;
                toggleButton.disabled = false;
                toggleButton.classList.remove('processing');
            }
            if (cameraElement) {
                cameraElement.classList.remove('processing');
            }
            // Force refresh page data after timeout
            refreshPageData();
        }, 1500); // 1.5 second timeout
    } else {
        // Revert UI on error
        if (toggleButton) {
            const currentEnabled = toggleButton.textContent.includes('Disable');
            updateCameraUI(cameraId, !currentEnabled);
            toggleButton.innerHTML = originalText;
            toggleButton.disabled = false;
            toggleButton.classList.remove('processing');
        }
        if (cameraElement) {
            cameraElement.classList.remove('processing');
        }
        showNotification('WebSocket not connected. Please refresh the page.', 'error');
        console.error('WebSocket not connected for camera toggle');
        
        // Force page reload to ensure data is updated
        setTimeout(() => {
            location.reload();
        }, 2000);
    }
}

// Update camera UI immediately for better responsiveness
function updateCameraUI(cameraId, enabled) {
    const cameraElement = document.querySelector(`[data-camera-id="${cameraId}"]`);
    if (cameraElement) {
        // Update status badge
        const statusBadge = cameraElement.querySelector('.camera-status-badge');
        if (statusBadge) {
            const badgeClass = enabled ? 'badge badge-modern bg-success-gradient' : 'badge badge-modern bg-secondary-gradient';
            const badgeText = enabled ? 'Active' : 'Inactive';
            statusBadge.className = badgeClass;
            statusBadge.textContent = badgeText;
        }
        
        // Update button
        const toggleButton = cameraElement.querySelector('button[onclick*="toggleCameraLive"]');
        if (toggleButton) {
            const buttonClass = enabled ? 'btn btn-sm btn-warning btn-modern btn-modern-enhanced' : 'btn btn-sm btn-success btn-modern btn-modern-enhanced';
            const buttonText = enabled ? 'Disable' : 'Enable';
            const iconClass = enabled ? 'bi-pause' : 'bi-play';
            
            toggleButton.className = buttonClass;
            toggleButton.innerHTML = `<i class="bi ${iconClass} me-1"></i>${buttonText}`;
        }
        
        // Add visual feedback
        cameraElement.classList.add('updating');
        setTimeout(() => {
            cameraElement.classList.remove('updating');
        }, 500);
    }
}

function testCameraLive(cameraId) {
    if (socket && socket.connected) {
        socket.emit('camera_test', {
            camera_id: cameraId
        });
        // Don't show testing notification to reduce spam
    } else {
        // Fallback to HTTP API if WebSocket not available
        console.warn('WebSocket not connected, falling back to HTTP API');
        testCameraHttp(cameraId, event?.target);
    }
}

function testCameraHttp(cameraId, buttonElement) {
    const button = buttonElement || document.querySelector(`button[onclick*="testCameraLive('${cameraId}')"]`);
    const originalText = button.innerHTML;
    
    // Show loading state immediately
    button.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Testing...';
    button.disabled = true;
    
    // Add visual feedback
    const cameraElement = document.querySelector(`[data-camera-id="${cameraId}"]`);
    if (cameraElement) {
        cameraElement.classList.add('testing');
    }
    
    fetch(`/cameras/test/${cameraId}`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.status === 'success') {
            showNotification(data.message, 'success');
            // Update UI to show success
            if (cameraElement) {
                const statusIndicator = cameraElement.querySelector('.camera-status-indicator');
                if (statusIndicator) {
                    statusIndicator.className = 'camera-status-indicator connected';
                }
            }
        } else if (data.status === 'warning') {
            showNotification(data.message, 'warning');
        } else {
            showNotification(data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Camera test failed: ' + error.message, 'error');
    })
    .finally(() => {
        button.innerHTML = originalText;
        button.disabled = false;
        if (cameraElement) {
            cameraElement.classList.remove('testing');
        }
        
        // Force page reload to ensure data is updated
        setTimeout(() => {
            location.reload();
        }, 2000);
    });
}

function refreshCamerasLive() {
    if (socket) {
        socket.emit('refresh_cameras');
    } else {
        showNotification('WebSocket not connected', 'error');
    }
}

// Show live update indicator
function showLiveUpdateIndicator() {
    const indicator = document.getElementById('liveIndicator');
    if (indicator) {
        indicator.style.display = 'inline-block';
        indicator.classList.add('pulse');
        
        setTimeout(() => {
            indicator.style.display = 'none';
            indicator.classList.remove('pulse');
        }, 2000);
    }
}

// Format timestamp for display
function formatTimestamp(timestamp) {
    try {
        const date = new Date(timestamp);
        return date.toLocaleString();
    } catch (error) {
        return timestamp;
    }
}

// Add activity item to feed
function addActivityItem(title, message, icon, type = 'info') {
    const activityFeed = document.getElementById('activityFeed');
    if (!activityFeed) return;
    
    const activityItem = document.createElement('div');
    activityItem.className = 'activity-item new';
    
    const iconClass = type === 'success' ? 'success' : type === 'warning' ? 'warning' : 'primary';
    
    activityItem.innerHTML = `
        <div class="activity-icon bg-${iconClass}-gradient">
            <i class="bi bi-${icon}"></i>
        </div>
        <div class="activity-content">
            <div class="activity-text">${title}: ${message}</div>
            <div class="activity-time">Just now</div>
        </div>
    `;
    
    // Insert at the top
    activityFeed.insertBefore(activityItem, activityFeed.firstChild);
    
    // Remove old items (keep only last 5)
    const items = activityFeed.querySelectorAll('.activity-item');
    if (items.length > 5) {
        items[items.length - 1].remove();
    }
    
    // Remove 'new' class after animation
    setTimeout(() => {
        activityItem.classList.remove('new');
    }, 300);
}

// Refresh live data
function refreshLiveData() {
    if (socket) {
        socket.emit('request_update', { type: 'all' });
        // Don't show notification for routine refresh
    } else {
        // Fallback to API calls when WebSocket is not available
        refreshDataViaAPI();
    }
}

// Fallback function to refresh data via API calls
function refreshDataViaAPI() {
    // Update system status
    fetch('/api/system/status')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateSystemStatus(data.data);
            }
        })
        .catch(error => console.error('Error updating system status:', error));
    
    // Update camera stats
    fetch('/api/cameras/stats')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateCameraStatus({ cameras: data.data.cameras });
            }
        })
        .catch(error => console.error('Error updating camera stats:', error));
    
    // Update recent detections
    fetch('/api/detections/recent?limit=10')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateDetectionFeed({ detections: data.data, count: data.count });
            }
        })
        .catch(error => console.error('Error updating detections:', error));
    
    // Don't show notification for routine API refresh
}

// ANPR Service Control Functions
function startANPRService() {
    controlANPRService('start');
}

function stopANPRService() {
    controlANPRService('stop');
}

function restartANPRService() {
    controlANPRService('restart');
}

function controlANPRService(action) {
    const button = document.getElementById(action + 'ServiceBtn');
    const originalText = button.innerHTML;
    
    // Show loading state
    button.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Processing...';
    button.disabled = true;
    
    fetch('/api/service/control', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ action: action })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification(data.message, 'success');
            addActivityItem('Service Control', `${action} command executed`, 'play-circle', 'success');
            
            // Update system status
            setTimeout(() => {
                if (socket) {
                    socket.emit('request_update', { type: 'system' });
                }
            }, 2000);
        } else {
            showNotification(data.error || 'Service control failed', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Service control failed: ' + error.message, 'error');
    })
    .finally(() => {
        // Restore button state
        button.innerHTML = originalText;
        button.disabled = false;
    });
}

// Camera Control Functions
function testCamera(cameraId) {
    const button = event.target;
    const originalText = button.innerHTML;
    
    // Show loading state
    button.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Testing...';
    button.disabled = true;
    
    fetch(`/cameras/test/${cameraId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification(data.message, 'success');
            addActivityItem('Camera Test', `Camera ${cameraId} test successful`, 'wifi', 'success');
        } else {
            showNotification(data.error || 'Camera test failed', 'error');
            addActivityItem('Camera Test', `Camera ${cameraId} test failed`, 'wifi', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Camera test failed: ' + error.message, 'error');
    })
    .finally(() => {
        // Restore button state
        button.innerHTML = originalText;
        button.disabled = false;
    });
}

function enableAllCameras() {
    if (confirm('Are you sure you want to enable all cameras?')) {
        // This would need to be implemented in the backend
        showNotification('Enable all cameras feature coming soon', 'info');
    }
}

function disableAllCameras() {
    if (confirm('Are you sure you want to disable all cameras?')) {
        // This would need to be implemented in the backend
        showNotification('Disable all cameras feature coming soon', 'info');
    }
}

// Live Detection Feed Functions
function refreshDetections() {
    fetch('/api/detections/recent?limit=10')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateDetectionFeed({ detections: data.data, count: data.count });
                showNotification('Detections refreshed', 'info');
            }
        })
        .catch(error => {
            console.error('Error refreshing detections:', error);
            showNotification('Failed to refresh detections', 'error');
        });
}

// Enhanced detection feed update
function updateDetectionFeed(data) {
    console.log('New detections:', data);
    
    // Update detection count in dashboard
    const detectionCountElement = document.getElementById('totalDetections');
    if (detectionCountElement) {
        detectionCountElement.textContent = data.count;
        detectionCountElement.classList.add('updated');
        setTimeout(() => detectionCountElement.classList.remove('updated'), 300);
    }
    
    // Update live detection feed (if section exists)
    if (data.detections && data.detections.length > 0) {
        const liveFeed = document.getElementById('liveDetectionFeed');
        if (liveFeed) {
            // Clear existing items
            liveFeed.innerHTML = '';
            
            // Add new detections
            // Ensure newest first
            const sorted = [...data.detections].sort((a, b) => (new Date(b.timestamp)) - (new Date(a.timestamp)));
            sorted.forEach((detection, index) => {
                const detectionItem = createDetectionItem(detection);
                liveFeed.appendChild(detectionItem);
                
                // Add animation delay for staggered effect
                setTimeout(() => {
                    detectionItem.classList.add('animate');
                }, index * 100);
            });
        }
        
        // Add to activity feed for latest detection
        const latestDetection = data.detections[0];
        
        // Get detection timestamp (could be in different formats)
        let detectionTime = null;
        if (latestDetection.timestamp) {
            detectionTime = new Date(latestDetection.timestamp).getTime();
        } else if (latestDetection.time) {
            detectionTime = new Date(latestDetection.time).getTime();
        }
        
        // Only show notification if:
        // 1. Initial page load is complete (don't show notifications for data loaded on page load)
        // 2. It's a verified plate
        // 3. It's actually a new detection (happened after page load or after last known detection)
        const isNewDetection = detectionTime && (
            detectionTime > pageLoadTime || 
            (lastDetectionTimestamp && detectionTime > lastDetectionTimestamp)
        );
        
        // Only show notification for truly new, verified detections (after initial load)
        if (initialLoadComplete && latestDetection.verification_status === 'VERIFIED' && latestDetection.plate && isNewDetection) {
            showNotification(`Verified plate detected: ${latestDetection.plate}`, 'success');
            // Update last detection timestamp
            if (detectionTime) {
                lastDetectionTimestamp = detectionTime;
            }
        }
        
        // Update last detection timestamp even if we don't show notification
        if (detectionTime && (!lastDetectionTimestamp || detectionTime > lastDetectionTimestamp)) {
            lastDetectionTimestamp = detectionTime;
        }
        
        // Add to activity feed (but only for new detections)
        if (isNewDetection) {
            addActivityItem('New Detection', `Plate ${latestDetection.plate || 'Unknown'} detected by ${latestDetection.camera_name || latestDetection.camera || 'Unknown Camera'}`, 'camera-video', 'success');
        }
    }
}

function createDetectionItem(detection) {
    const item = document.createElement('div');
    item.className = 'detection-item new';
    
    const statusClass = detection.verification_status === 'VERIFIED' ? 'verified' : 'not-verified';
    const iconClass = detection.verification_status === 'VERIFIED' ? 'check-circle' : 'exclamation-circle';
    const iconBgClass = detection.verification_status === 'VERIFIED' ? 'success' : 'warning';
    
    // Optional image thumbnails
    const fullRaw = detection.image_full_raw || '';
    const fullAnnotated = detection.image_full_annotated || '';
    const crop = detection.image_plate_crop || '';
    const hasAnyImage = !!(fullRaw || fullAnnotated || crop);
    
    let imagesHtml = '';
    if (hasAnyImage) {
        imagesHtml = `
            <div class="detection-images">
                ${fullAnnotated ? `<img src="${fullAnnotated}" alt="Annotated" class="detection-thumb annotated" onclick="previewDetectionImage('${fullAnnotated}')">` : ''}
                ${fullRaw ? `<img src="${fullRaw}" alt="Full Frame" class="detection-thumb full" onclick="previewDetectionImage('${fullRaw}')">` : ''}
                ${crop ? `<img src="${crop}" alt="Plate Crop" class="detection-thumb crop" onclick="previewDetectionImage('${crop}')">` : ''}
            </div>
        `;
    }
    
    item.innerHTML = `
        <div class="detection-icon bg-${iconBgClass}-gradient">
            <i class="bi bi-${iconClass}"></i>
        </div>
        <div class="detection-content">
            <div class="detection-text">
                <span class="detection-plate">${detection.plate}</span>
                <span class="detection-camera">detected by ${detection.camera_name || detection.camera || 'Unknown Camera'}</span>
                <span class="detection-status ${statusClass}">${detection.verification_status}</span>
            </div>
            ${imagesHtml}
            <div class="detection-time">${formatTimestamp(detection.timestamp)}</div>
        </div>
    `;
    
    return item;
}

// Simple image preview (uses Bootstrap modal if available, else opens new tab)
function previewDetectionImage(url) {
    try {
        // Lightbox overlay with blur & single-click close
        const overlay = document.createElement('div');
        overlay.className = 'lightbox-overlay';
        overlay.innerHTML = `<img src="${url}" alt="Preview">`;
        overlay.addEventListener('click', () => overlay.remove());
        document.body.appendChild(overlay);
    } catch (e) {
        window.open(url, '_blank');
    }
}

// Initialize live feed toggle
function initializeLiveFeedToggle() {
    const toggle = document.getElementById('liveFeedToggle');
    if (toggle) {
        toggle.addEventListener('change', function() {
            if (this.checked) {
                // Enable live updates
                if (socket) {
                    socket.emit('join_room', { room: 'detections' });
                    showNotification('Live detection feed enabled', 'info');
                } else {
                    // Fallback to periodic refresh
                    startPeriodicRefresh();
                    showNotification('Live detection feed enabled (API mode)', 'info');
                }
            } else {
                // Disable live updates
                if (socket) {
                    socket.emit('leave_room', { room: 'detections' });
                } else {
                    stopPeriodicRefresh();
                }
                showNotification('Live detection feed disabled', 'warning');
            }
        });
    }
}

// Periodic refresh for fallback mode

function startPeriodicRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    
    // Refresh every 5 seconds
    refreshInterval = setInterval(() => {
        refreshDataViaAPI();
    }, 5000);
    
    console.log('Periodic refresh started');
}

function stopPeriodicRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
    console.log('Periodic refresh stopped');
}

// Load initial data on page load
function loadInitialData() {
    console.log('Loading initial data...');
    
    // Show loading state for stats cards
    showLoadingState();
    
    // Load system status
    fetch('/api/system/status')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateSystemStatus(data.data);
            }
        })
        .catch(error => {
            console.error('Error loading system status:', error);
            showErrorState('System Status');
        });
    
    // Load camera stats
    fetch('/api/cameras/stats')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateCameraStatus({ cameras: data.data.cameras });
            }
        })
        .catch(error => {
            console.error('Error loading camera stats:', error);
            showErrorState('Camera Stats');
        });
    
    // Load recent detections
    fetch('/api/detections/recent?limit=10')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateDetectionFeed({ detections: data.data, count: data.count });
            }
        })
        .catch(error => {
            console.error('Error loading detections:', error);
            showErrorState('Detections');
        });
    
    // Load detection stats
    fetch('/api/detections/stats')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateDetectionStats(data.data);
            }
        })
        .catch(error => {
            console.error('Error loading detection stats:', error);
            showErrorState('Detection Stats');
        });
    
    console.log('Initial data loaded');
}

// Show loading state for stats cards
function showLoadingState() {
    const statsElements = [
        'total-detections',
        'verified-detections', 
        'unverified-detections',
        'today-detections'
    ];
    
    statsElements.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = '...';
            element.style.color = '#6c757d';
        }
    });
}

// Show error state for stats cards
function showErrorState(type) {
    console.warn(`Failed to load ${type}, showing fallback data`);
    
    // Set fallback values
    const totalDetectionsElement = document.getElementById('total-detections');
    if (totalDetectionsElement) {
        totalDetectionsElement.textContent = '0';
        totalDetectionsElement.style.color = '#dc3545';
    }
    
    const verifiedDetectionsElement = document.getElementById('verified-detections');
    if (verifiedDetectionsElement) {
        verifiedDetectionsElement.textContent = '0';
        verifiedDetectionsElement.style.color = '#dc3545';
    }
    
    const notVerifiedDetectionsElement = document.getElementById('unverified-detections');
    if (notVerifiedDetectionsElement) {
        notVerifiedDetectionsElement.textContent = '0';
        notVerifiedDetectionsElement.style.color = '#dc3545';
    }
    
    const todayDetectionsElement = document.getElementById('today-detections');
    if (todayDetectionsElement) {
        todayDetectionsElement.textContent = '0';
        todayDetectionsElement.style.color = '#dc3545';
    }
}


// Refresh detections
function refreshDetections() {
    console.log('Refreshing detections...');
    
    // Load recent detections
    fetch('/api/detections/recent?limit=10')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateDetectionFeed({ detections: data.data, count: data.count });
                // Don't show notification for routine refresh
            }
        })
        .catch(error => {
            console.error('Error refreshing detections:', error);
            showNotification('Error refreshing detections', 'error');
        });
}

// Refresh all dashboard statistics
function refreshStats() {
    console.log('Refreshing all dashboard statistics...');
    
    // Show loading state
    const refreshBtn = document.querySelector('button[onclick="refreshStats()"]');
    const originalText = refreshBtn.innerHTML;
    refreshBtn.innerHTML = '<i class="bi bi-hourglass-split me-2"></i>Refreshing...';
    refreshBtn.disabled = true;
    
    // Refresh all data
    Promise.all([
        // System status
        fetch('/api/system/status').then(r => r.json()),
        // Camera stats
        fetch('/api/cameras/stats').then(r => r.json()),
        // Recent detections
        fetch('/api/detections/recent?limit=10').then(r => r.json()),
        // Detection stats
        fetch('/api/detections/stats').then(r => r.json())
    ])
    .then(([systemData, cameraData, detectionData, statsData]) => {
        // Update system status
        if (systemData.success) {
            updateSystemStatus(systemData.data);
        }
        
        // Update camera status
        if (cameraData.success) {
            updateCameraStatus({ cameras: cameraData.data.cameras });
        }
        
        // Update detection feed
        if (detectionData.success) {
            updateDetectionFeed({ detections: detectionData.data, count: detectionData.count });
        }
        
        // Update stats cards
        if (statsData.success) {
            updateDetectionStats(statsData.data);
        }
        
        // Add activity item
        addActivityItem('Dashboard', 'All statistics refreshed', 'arrow-clockwise', 'success');
        
        // Don't show notification for routine refresh
    })
    .catch(error => {
        console.error('Error refreshing dashboard:', error);
        showNotification('Error refreshing dashboard', 'error');
    })
    .finally(() => {
        // Restore button state
        refreshBtn.innerHTML = originalText;
        refreshBtn.disabled = false;
    });
}

// Show notification function moved to enhanced notification system below

// Security functions
function initializeSecurity() {
    // Check session validity every 5 minutes
    setInterval(checkSessionValidity, 300000);
    
    // Check session on page visibility change
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            checkSessionValidity();
        }
    });
    
    // Warn user before session expires (5 minutes before)
    setInterval(warnSessionExpiry, 3000000); // 50 minutes
}

function checkSessionValidity() {
    fetch('/check-session')
        .then(response => response.json())
        .then(data => {
            if (!data.valid) {
                // Session expired, redirect to login
                window.location.href = '/login';
            }
        })
        .catch(error => {
            console.error('Session check failed:', error);
            // On error, assume session is invalid
            window.location.href = '/login';
        });
}

function warnSessionExpiry() {
    // Show warning 5 minutes before session expires
    if (confirm('Your session will expire in 5 minutes. Do you want to stay logged in?')) {
        // Refresh session by making a request
        fetch('/check-session')
            .then(response => response.json())
            .then(data => {
                if (data.valid) {
                    // Session refreshed
                    console.log('Session refreshed');
                } else {
                    window.location.href = '/login';
                }
            });
    }
}

// Initialize admin panel
function initializeAdminPanel() {
    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Initialize WebSocket connection
    initializeWebSocket();
    
    // Mark initial load as complete after initial data loads
    // This prevents showing notifications for old detections loaded on page load
    setTimeout(function() {
        initialLoadComplete = true;
        console.log('✅ Initial page load complete - notifications enabled for new detections only');
    }, 3000); // 3 seconds should be enough for initial data to load
    
    // Load initial data
    loadInitialData();
    
    // Initialize popovers
    var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    var popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
    
    // Auto-hide alerts
    autoHideAlerts();
    
    // Initialize real-time updates
    initializeRealTimeUpdates();
    
    // Initialize form validations
    initializeFormValidations();
    
    // Initialize animations
    initializeAnimations();
    
    // Initialize smooth scrolling
    initializeSmoothScrolling();
    
    // Initialize button spam prevention
    initializeButtonSpamPrevention();
}

// Prevent button spam clicking
function initializeButtonSpamPrevention() {
    document.addEventListener('click', function(e) {
        const button = e.target.closest('button');
        if (button && button.disabled) {
            e.preventDefault();
            e.stopPropagation();
            return false;
        }
    });
}

// Refresh page data after operations
function refreshPageData() {
    // Show refresh indicator
    showLiveUpdateIndicator();
    
    // Refresh camera status
    if (socket && socket.connected) {
        socket.emit('refresh_cameras');
    } else {
        // Fallback to API refresh
        fetch('/api/cameras/stats')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    updateCameraStatus({ cameras: data.data.cameras });
                }
            })
            .catch(error => console.error('Error refreshing camera stats:', error));
    }
    
    // Refresh system status
    fetch('/api/system/status')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateSystemStatus(data.data);
            }
        })
        .catch(error => console.error('Error refreshing system status:', error));
    
    // Refresh detection stats
    fetch('/api/detections/stats')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateDetectionStats(data.data);
            }
        })
        .catch(error => console.error('Error refreshing detection stats:', error));
}

// Auto-hide alerts after 5 seconds
function autoHideAlerts() {
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            if (alert && alert.parentNode) {
                alert.style.transition = 'opacity 0.5s ease';
                alert.style.opacity = '0';
                setTimeout(() => {
                    if (alert && alert.parentNode) {
                        alert.remove();
                    }
                }, 500);
            }
        }, 5000);
    });
}

// Initialize real-time updates
function initializeRealTimeUpdates() {
    // Only start real-time updates on dashboard
    if (window.location.pathname === '/' || window.location.pathname === '/dashboard') {
        startRealTimeUpdates();
    }
}

// Start real-time updates
let dashboardRefreshInterval;

function startRealTimeUpdates() {
    dashboardRefreshInterval = setInterval(() => {
        updateDashboardStats();
    }, 30000); // Update every 30 seconds
}

// Stop real-time updates
function stopRealTimeUpdates() {
    if (dashboardRefreshInterval) {
        clearInterval(dashboardRefreshInterval);
    }
}

// Update dashboard statistics
function updateDashboardStats() {
    fetch('/api/stats')
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            console.error('Error fetching stats:', data.error);
            return;
        }
        
        // Update stats elements if they exist
        updateElement('today-detections', data.today_detections || 0);
        updateElement('total-detections', data.total_detections || 0);
        updateElement('verified-detections', data.today_verified || 0);
        updateElement('verification-rate', (data.verification_rate || 0) + '%');
    })
    .catch(error => {
        console.error('Error updating stats:', error);
    });
}

// Update element with animation
function updateElement(id, value) {
    const element = document.getElementById(id);
    if (element) {
        const oldValue = element.textContent;
        if (oldValue !== value.toString()) {
            element.style.transition = 'all 0.3s ease';
            element.style.transform = 'scale(1.1)';
            element.textContent = value;
            setTimeout(() => {
                element.style.transform = 'scale(1)';
            }, 300);
        }
    }
}

// Initialize form validations
function initializeFormValidations() {
    // Real-time form validation
    const forms = document.querySelectorAll('form[data-validate]');
    forms.forEach(form => {
        const inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            input.addEventListener('blur', () => validateField(input));
            input.addEventListener('input', () => clearFieldError(input));
        });
    });
}

// Validate individual field
function validateField(field) {
    const value = field.value.trim();
    const type = field.type;
    const required = field.hasAttribute('required');
    
    clearFieldError(field);
    
    if (required && !value) {
        showFieldError(field, 'This field is required');
        return false;
    }
    
    if (value) {
        switch (type) {
            case 'email':
                if (!isValidEmail(value)) {
                    showFieldError(field, 'Please enter a valid email address');
                    return false;
                }
                break;
            case 'url':
                if (!isValidUrl(value)) {
                    showFieldError(field, 'Please enter a valid URL');
                    return false;
                }
                break;
            case 'number':
                if (isNaN(value)) {
                    showFieldError(field, 'Please enter a valid number');
                    return false;
                }
                break;
        }
    }
    
    return true;
}

// Show field error
function showFieldError(field, message) {
    clearFieldError(field);
    
    field.classList.add('is-invalid');
    
    const errorDiv = document.createElement('div');
    errorDiv.className = 'invalid-feedback';
    errorDiv.textContent = message;
    
    field.parentNode.appendChild(errorDiv);
}

// Clear field error
function clearFieldError(field) {
    field.classList.remove('is-invalid');
    
    const errorDiv = field.parentNode.querySelector('.invalid-feedback');
    if (errorDiv) {
        errorDiv.remove();
    }
}

// Validate email
function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

// Validate URL
function isValidUrl(url) {
    try {
        new URL(url);
        return true;
    } catch {
        return false;
    }
}

// Show loading state
function showLoading(element) {
    if (typeof element === 'string') {
        element = document.getElementById(element);
    }
    
    if (element) {
        element.classList.add('loading');
        element.disabled = true;
    }
}

// Hide loading state
function hideLoading(element) {
    if (typeof element === 'string') {
        element = document.getElementById(element);
    }
    
    if (element) {
        element.classList.remove('loading');
        element.disabled = false;
    }
}

// Show success message
function showSuccess(message, duration = 5000) {
    showNotification(message, 'success', duration);
}

// Show error message
function showError(message, duration = 5000) {
    showNotification(message, 'danger', duration);
}

// Show warning message
function showWarning(message, duration = 5000) {
    showNotification(message, 'warning', duration);
}

// Show info message
function showInfo(message, duration = 5000) {
    showNotification(message, 'info', duration);
}

// Show notification function moved to enhanced notification system below

// Get icon for notification type
function getIconForType(type) {
    const icons = {
        'success': 'check-circle',
        'danger': 'exclamation-triangle',
        'warning': 'exclamation-triangle',
        'info': 'info-circle'
    };
    return icons[type] || 'info-circle';
}

// Confirm dialog
function confirmDialog(message, callback) {
    if (confirm(message)) {
        if (typeof callback === 'function') {
            callback();
        }
        return true;
    }
    return false;
}

// Format date
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}

// Format number with commas
function formatNumber(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// Debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Throttle function
function throttle(func, limit) {
    let inThrottle;
    return function() {
        const args = arguments;
        const context = this;
        if (!inThrottle) {
            func.apply(context, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Search functionality
function initializeSearch(inputId, tableId) {
    const searchInput = document.getElementById(inputId);
    const table = document.getElementById(tableId);
    
    if (searchInput && table) {
        const debouncedSearch = debounce((searchTerm) => {
            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                if (text.includes(searchTerm.toLowerCase())) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        }, 300);
        
        searchInput.addEventListener('input', (e) => {
            debouncedSearch(e.target.value);
        });
    }
}

// Table sorting
function sortTable(tableId, columnIndex, ascending = true) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    
    rows.sort((a, b) => {
        const aText = a.cells[columnIndex].textContent.trim();
        const bText = b.cells[columnIndex].textContent.trim();
        
        // Try to parse as numbers
        const aNum = parseFloat(aText);
        const bNum = parseFloat(bText);
        
        if (!isNaN(aNum) && !isNaN(bNum)) {
            return ascending ? aNum - bNum : bNum - aNum;
        }
        
        // Sort as strings
        return ascending ? 
            aText.localeCompare(bText) : 
            bText.localeCompare(aText);
    });
    
    // Re-append sorted rows
    rows.forEach(row => tbody.appendChild(row));
}

// Export table to CSV
function exportTableToCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    const rows = table.querySelectorAll('tr');
    const csv = [];
    
    rows.forEach(row => {
        const cells = row.querySelectorAll('th, td');
        const rowData = Array.from(cells).map(cell => {
            return '"' + cell.textContent.replace(/"/g, '""') + '"';
        });
        csv.push(rowData.join(','));
    });
    
    const csvContent = csv.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || 'export.csv';
    link.click();
    
    window.URL.revokeObjectURL(url);
}

// Copy to clipboard
function copyToClipboard(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            showSuccess('Copied to clipboard!');
        });
    } else {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = text;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showSuccess('Copied to clipboard!');
    }
}

// Initialize all search inputs
document.addEventListener('DOMContentLoaded', function() {
    // Initialize admin panel
    initializeAdminPanel();
    
    // Initialize search for plates table
    initializeSearch('searchInput', 'platesTable');
    
    // Initialize search for detections table
    initializeSearch('search', 'detectionsTable');
    
    // Initialize sidebar
    initializeSidebar();
    
    // Initialize camera dropdown behavior
    initializeCameraDropdowns();
});

// Sidebar functionality
function initializeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebarToggleMobile = document.getElementById('sidebarToggleMobile');
    
    // Mobile sidebar toggle
    if (sidebarToggleMobile) {
        sidebarToggleMobile.addEventListener('click', function() {
            sidebar.classList.add('show');
            sidebarOverlay.classList.add('show');
            document.body.style.overflow = 'hidden';
        });
    }
    
    // Close sidebar (mobile)
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function() {
            sidebar.classList.remove('show');
            sidebarOverlay.classList.remove('show');
            document.body.style.overflow = '';
        });
    }
    
    // Close sidebar when clicking overlay
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', function() {
            sidebar.classList.remove('show');
            sidebarOverlay.classList.remove('show');
            document.body.style.overflow = '';
        });
    }
    
    // Close sidebar on escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            sidebar.classList.remove('show');
            sidebarOverlay.classList.remove('show');
            document.body.style.overflow = '';
        }
    });
    
    // Handle window resize
    window.addEventListener('resize', function() {
        if (window.innerWidth > 992) {
            sidebar.classList.remove('show');
            sidebarOverlay.classList.remove('show');
            document.body.style.overflow = '';
        }
    });
}

// Initialize camera dropdown behavior
function initializeCameraDropdowns() {
    // Let Bootstrap handle dropdown behavior naturally
    // Just ensure proper z-index
    const dropdowns = document.querySelectorAll('.camera-card .dropdown');
    
    dropdowns.forEach(dropdown => {
        const button = dropdown.querySelector('[data-bs-toggle="dropdown"]');
        const menu = dropdown.querySelector('.dropdown-menu');
        
        if (button && menu) {
            // Handle dropdown show event - just set z-index
            button.addEventListener('show.bs.dropdown', function() {
                setTimeout(() => {
                    menu.style.zIndex = '999999';
                }, 10);
            });
        }
    });
}

// Initialize animations
function initializeAnimations() {
    // Add hover effects to interactive elements
    const interactiveElements = document.querySelectorAll('.btn, .card, .nav-link');
    interactiveElements.forEach(element => {
        element.classList.add('hover-lift');
    });
    
    // Add scale effect to buttons
    const buttons = document.querySelectorAll('.btn');
    buttons.forEach(button => {
        button.classList.add('hover-scale');
    });
    
    // Add glow effect to primary buttons
    const primaryButtons = document.querySelectorAll('.btn-primary');
    primaryButtons.forEach(button => {
        button.classList.add('hover-glow');
    });
}

// Search functionality
function performSearch() {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        const searchTerm = searchInput.value.trim();
        if (searchTerm) {
            // Perform search logic here
            console.log('Searching for:', searchTerm);
            // You can add actual search functionality here
        }
    }
}

// Clear filters function for detections page
function clearFilters() {
    const form = document.getElementById('filterForm');
    if (form) {
        form.reset();
        // Submit the form to clear all filters
        form.submit();
    }
}

// Initialize smooth scrolling
function initializeSmoothScrolling() {
    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

// Enhanced notification system with proper stack management
let notificationStack = [];
let maxNotifications = 3;
let notificationContainer = null;

function initializeNotificationContainer() {
    if (!notificationContainer) {
        notificationContainer = document.createElement('div');
        notificationContainer.id = 'notification-container';
        notificationContainer.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
            pointer-events: none;
        `;
        document.body.appendChild(notificationContainer);
    }
}

function showNotification(message, type, duration = 5000) {
    // Initialize container if needed
    initializeNotificationContainer();
    
    // Don't show duplicate notifications
    if (notificationStack.some(n => n.message === message && n.type === type)) {
        return;
    }
    
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show notification-item`;
    
    notification.style.cssText = `
        min-width: 300px;
        max-width: 400px;
        margin-bottom: 10px;
        pointer-events: auto;
        transform: translateX(100%);
        transition: transform 0.3s ease;
    `;
    
    notification.innerHTML = `
        <div class="d-flex align-items-center">
            <i class="bi bi-${getIconForType(type)} me-3 fs-4"></i>
            <div class="flex-grow-1">
                <strong>${getTitleForType(type)}</strong><br>
                <small>${message}</small>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    // Add to stack
    notificationStack.push({
        element: notification,
        message: message,
        type: type,
        id: Date.now()
    });
    
    // Remove oldest if stack is full
    if (notificationStack.length > maxNotifications) {
        const oldest = notificationStack.shift();
        if (oldest.element && oldest.element.parentNode) {
            removeNotificationFromStack(oldest.element);
        }
    }
    
    notificationContainer.appendChild(notification);
    
    // Animate in
    setTimeout(() => {
        notification.style.transform = 'translateX(0)';
    }, 10);
    
    // Auto-remove after duration
    setTimeout(() => {
        removeNotificationFromStack(notification);
    }, duration);
}

function removeNotificationFromStack(notification) {
    if (notification && notification.parentNode) {
        notification.style.transform = 'translateX(100%)';
        notification.style.opacity = '0';
        setTimeout(() => {
            if (notification && notification.parentNode) {
                notification.remove();
                // Remove from stack
                notificationStack = notificationStack.filter(n => n.element !== notification);
            }
        }, 300);
    }
}

// Get title for notification type
function getTitleForType(type) {
    const titles = {
        'success': 'Success',
        'danger': 'Error',
        'warning': 'Warning',
        'info': 'Information'
    };
    return titles[type] || 'Notification';
}

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    stopRealTimeUpdates();
});
