fetch('/firebase-config')
  .then(response => response.json())
  .then(firebaseConfig => {
    // Use compat version for compatibility with existing code
    if (!firebase.apps.length) {
      firebase.initializeApp(firebaseConfig);
    }
    const db = firebase.database();
    db.ref("site_status/enabled").on("value", (snapshot) => {
      const enabled = snapshot.val();
      if (enabled === false) {
        document.body.innerHTML = `
          <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;">
            <h1 style="color:#d32f2f;font-size:2.5rem;">Site Under Maintenance</h1>
            <p style="font-size:1.2rem;">We are currently performing scheduled maintenance.<br>Please check back later.</p>
          </div>
        `;
      }
    });
  }); 