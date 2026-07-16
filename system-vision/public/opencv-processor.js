// OpenCV.js integration for webcam processing
// This module handles webcam capture and frame processing using OpenCV.js

// Polyfill for navigator.mediaDevices (for older browsers)
if (navigator.mediaDevices === undefined) {
    navigator.mediaDevices = {};
}

// Polyfill getUserMedia for older browsers
if (navigator.mediaDevices.getUserMedia === undefined) {
    navigator.mediaDevices.getUserMedia = function(constraints) {
        // First get the legacy getUserMedia if present
        const getUserMedia = navigator.getUserMedia ||
                           navigator.webkitGetUserMedia ||
                           navigator.mozGetUserMedia ||
                           navigator.msGetUserMedia;

        // Some browsers don't implement it - return a rejected promise with an error
        if (!getUserMedia) {
            return Promise.reject(new Error('getUserMedia is not implemented in this browser. ' +
                'Please use a modern browser (Chrome, Firefox, Edge, Safari).'));
        }

        // Wrap the legacy API with a Promise
        return new Promise(function(resolve, reject) {
            getUserMedia.call(navigator, constraints, resolve, reject);
        });
    };
}

class OpenCVWebcamProcessor {
    constructor(videoElement, canvasElement, detectionEndpoint) {
        this.video = videoElement;
        this.canvas = canvasElement;
        this.detectionEndpoint = detectionEndpoint;
        this.isProcessing = false;
        this.animationFrameId = null;
        this.cap = null;
        this.src = null;
        this.dst = null;
    }

    async initialize() {
        // Wait for OpenCV.js to be ready
        await new Promise((resolve, reject) => {
            if (typeof cv !== 'undefined' && cv.Mat) {
                console.log('OpenCV.js already loaded and ready');
                resolve();
            } else {
                console.log('Waiting for OpenCV.js to load...');
                const timeout = setTimeout(() => {
                    reject(new Error('OpenCV.js loading timeout after 30 seconds'));
                }, 30000);

                document.addEventListener('opencv-ready', () => {
                    clearTimeout(timeout);
                    console.log('OpenCV.js loaded via opencv-ready event');
                    resolve();
                }, { once: true });
            }
        });

        console.log('OpenCV.js is ready');

        // Set canvas size to match video
        this.canvas.width = this.video.videoWidth || 640;
        this.canvas.height = this.video.videoHeight || 640;

        // Initialize OpenCV matrices
        this.src = new cv.Mat(this.canvas.height, this.canvas.width, cv.CV_8UC4);
        this.dst = new cv.Mat(this.canvas.height, this.canvas.width, cv.CV_8UC4);
        this.cap = new cv.VideoCapture(this.video);

        return true;
    }

    async processFrame() {
        if (!this.isProcessing) return;

        try {
            // Capture frame from video
            this.cap.read(this.src);

            // Convert to format suitable for detection (BGR)
            let frame = new cv.Mat();
            cv.cvtColor(this.src, frame, cv.COLOR_RGBA2RGB);

            // Convert frame to JPEG for sending to backend
            let canvas = document.createElement('canvas');
            canvas.width = frame.cols;
            canvas.height = frame.rows;
            cv.imshow(canvas, frame);

            // Convert canvas to blob
            const blob = await new Promise(resolve => {
                canvas.toBlob(resolve, 'image/jpeg', 0.8);
            });

            // Send to backend for detection
            const formData = new FormData();
            formData.append('frame', blob);

            try {
                const response = await fetch(this.detectionEndpoint, {
                    method: 'POST',
                    body: formData,
                });

                if (response.ok) {
                    const resultBlob = await response.blob();
                    const img = await createImageBitmap(resultBlob);

                    // Draw result on canvas
                    const ctx = this.canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, this.canvas.width, this.canvas.height);
                } else {
                    // If detection fails, just show the original frame
                    cv.imshow(this.canvas, this.src);
                }
            } catch (fetchError) {
                console.warn('Detection request failed:', fetchError);
                // Show original frame if detection fails
                cv.imshow(this.canvas, this.src);
            }

            frame.delete();

        } catch (error) {
            console.error('Frame processing error:', error);
        }

        // Continue processing
        if (this.isProcessing) {
            this.animationFrameId = requestAnimationFrame(() => this.processFrame());
        }
    }

    start() {
        if (this.isProcessing) return;

        this.isProcessing = true;
        this.processFrame();
    }

    stop() {
        this.isProcessing = false;

        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }
    }

    cleanup() {
        this.stop();

        if (this.src) this.src.delete();
        if (this.dst) this.dst.delete();
        this.src = null;
        this.dst = null;
        this.cap = null;
    }
}

// Global processor instance
window.opencvProcessor = null;
window.webcamStream = null;

// Initialize webcam and processor together
window.initWebcamAndProcessor = async function(videoElementId, canvasElementId, detectionEndpoint) {
    try {
        // Get elements
        const videoElement = document.getElementById(videoElementId);
        const canvasElement = document.getElementById(canvasElementId);

        if (!videoElement || !canvasElement) {
            throw new Error('Video or canvas element not found');
        }

        // Check if MediaDevices API is available
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            throw new Error('MediaDevices API not available. Please ensure:\n' +
                '1. You are using HTTPS (or localhost)\n' +
                '2. Your browser supports getUserMedia\n' +
                '3. Camera permissions are granted');
        }

        // Request webcam access
        const constraints = {
            video: {
                width: { ideal: 1280 },
                height: { ideal: 720 }
            },
            audio: false
        };

        console.log('Requesting webcam access...');
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        window.webcamStream = stream;
        console.log('Webcam access granted');

        // Connect stream to video element
        videoElement.srcObject = stream;
        await videoElement.play();

        // Wait for video to be ready
        await new Promise(resolve => {
            if (videoElement.readyState >= 2) {
                resolve();
            } else {
                videoElement.addEventListener('loadeddata', resolve, { once: true });
            }
        });


        // Initialize processor
        if (window.opencvProcessor) {
            window.opencvProcessor.cleanup();
        }

        window.opencvProcessor = new OpenCVWebcamProcessor(
            videoElement,
            canvasElement,
            detectionEndpoint
        );

        await window.opencvProcessor.initialize();

        console.log('Webcam and OpenCV processor initialized successfully');
        return true;
    } catch (error) {
        console.error('Failed to initialize webcam and processor:', error);

        // Provide more specific error messages
        if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
            throw new Error('Camera permission denied. Please allow camera access and try again.');
        } else if (error.name === 'NotFoundError' || error.name === 'DevicesNotFoundError') {
            throw new Error('No camera found. Please connect a camera and try again.');
        } else if (error.name === 'NotReadableError' || error.name === 'TrackStartError') {
            throw new Error('Camera is already in use by another application.');
        } else if (error.name === 'OverconstrainedError' || error.name === 'ConstraintNotSatisfiedError') {
            throw new Error('Camera does not support the requested resolution.');
        } else if (error.name === 'SecurityError') {
            throw new Error('Camera access is not allowed in this context. Please use HTTPS or localhost.');
        } else if (error.message && error.message.includes('MediaDevices API not available')) {
            throw error; // Already have a good error message
        }

        throw error;
    }
};

// Start processing
window.startOpenCVProcessing = function() {
    if (window.opencvProcessor) {
        window.opencvProcessor.start();
    }
};

// Stop processing
window.stopOpenCVProcessing = function() {
    if (window.opencvProcessor) {
        window.opencvProcessor.stop();
    }
};

// Cleanup
window.cleanupOpenCVProcessor = function() {
    if (window.opencvProcessor) {
        window.opencvProcessor.cleanup();
        window.opencvProcessor = null;
    }

    // Stop webcam stream
    if (window.webcamStream) {
        window.webcamStream.getTracks().forEach(track => track.stop());
        window.webcamStream = null;
    }
};

// Signal when OpenCV.js is loaded
// This handles cases where opencv-processor.js loads after opencv.js is already ready
(function checkOpenCVReady() {
    if (typeof cv !== 'undefined' && cv.Mat) {
        console.log('OpenCV.js already loaded when opencv-processor.js initialized');
        document.dispatchEvent(new Event('opencv-ready'));
    } else {
        console.log('OpenCV.js not yet loaded, waiting for Module.onRuntimeInitialized');
    }
})();


