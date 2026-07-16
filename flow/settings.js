module.exports = {
  // Listen on all interfaces so the container is reachable
  uiHost: "0.0.0.0",
  uiPort: 1880,

  // Served under /flow on the device's single origin (nginx proxies /flow/ →
  // flow:1880/flow/), so the WASM UI reaches it same-origin through the hub's
  // reverse proxy. Both the editor (admin) and HTTP-in nodes live under /flow.
  httpAdminRoot: "/flow",
  httpNodeRoot: "/flow",

  // Disable admin authentication for internal network use
  // Uncomment and configure if you need authentication:
  // adminAuth: {
  //   type: "credentials",
  //   users: [{ username: "admin", password: "<bcrypt-hash>", permissions: "*" }]
  // },

  // Allow the editor and API to be embedded in iframes
  httpNodeCors: {
    origin: "*",
    methods: "GET,PUT,POST,DELETE",
  },

  // Allow iframe embedding by the WASM UI on the same origin (served directly,
  // behind :443 mTLS, or through the hub's 127.0.0.1 reverse proxy).
  headers: {
    "Content-Security-Policy":
      "frame-ancestors 'self' http://localhost:* http://127.0.0.1:*",
  },

  // Persist flows and credentials in the mounted volume
  flowFile: "flows.json",
  // Secret used to encrypt stored credentials. Override per deployment via
  // NODE_RED_CREDENTIAL_SECRET; changing it invalidates existing credentials.
  credentialSecret: process.env.NODE_RED_CREDENTIAL_SECRET || "conecsa-node-red-secret",

  // Logging
  logging: {
    console: {
      level: "info",
      metrics: false,
      audit: false,
    },
  },

  // Editor theme
  // theme-auto.css contains the Conecsa industrial dark theme used by the
  // embedded editor and the standalone Node-RED UI.
  editorTheme: {
    page: {
      title: "Conecsa Flow Editor",
      css: "/data/theme-auto.css",
    },
    header: {
      title: "Conecsa Flow",
      image: "/data/conecsa_white_logo.png",
    },
    palette: {
      // Pre-install packages are handled at container build time (package.json)
    },
  },
};
