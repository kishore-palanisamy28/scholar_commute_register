// Maintenance mode check
fetch('/firebase-config')
  .then(response => response.json())
  .then(firebaseConfig => {
    if (!firebase.apps.length) {
      firebase.initializeApp(firebaseConfig);
    }
    const db = firebase.database();
    db.ref("site_status/enabled").on("value", (snapshot) => {
      const enabled = snapshot.val();
      console.log("[DEBUG] Maintenance status from Firebase:", enabled);
      // Robust check for all falsey/disabled values
      if (
        enabled === false ||
        enabled === "false" ||
        enabled === 0 ||
        enabled === "0" ||
        enabled === null ||
        enabled === undefined
      ) {
        document.body.innerHTML = `
          <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;">
            <h1 style="color:#d32f2f;font-size:2.5rem;">Server Unavailable</h1>
            <p style="font-size:1.2rem;">The server is currently unavailable due to maintenance.<br>Please check back later.</p>
          </div>
        `;
        return;
      }
      // Only run main app logic if enabled is true
      runMainApp(firebaseConfig);
    });
  });

function runMainApp(firebaseConfig) {
  let sampleCount = 0;
  const db = firebase.firestore();

  const busStopSelect = document.getElementById("busStop");

  db.collection("default_routes")
    .get()
    .then((querySnapshot) => {
      const stopsSet = new Set();
      querySnapshot.forEach((doc) => {
        const stops = doc.data().stops || [];
        stops.forEach((stop) => stopsSet.add(stop));
      });
      busStopSelect.innerHTML = '<option value="">Select your stop</option>';
      Array.from(stopsSet)
        .sort()
        .forEach((stop) => {
          const option = document.createElement("option");
          option.value = stop;
          option.textContent = stop;
          busStopSelect.appendChild(option);
        });
    });

  const form = document.getElementById("infoForm");
  const video = document.getElementById("video");
  const sampleCountSpan = document.getElementById("sampleCount");
  const sampleCounter = document.getElementById("sampleCounter");

  let intervalId = null;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("name").value;
    const email = document.getElementById("email").value;
    const password = document.getElementById("dob").value;
    const role = document.getElementById("role").value;
    const busStop = document.getElementById("busStop").value;

    const res = await fetch("/start-face-collection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        email: email,
        dob: password,
        role: role,
        busStop: busStop,
      }),
    });

    const result = await res.json();
    if (result.message === "Collection started and student registered") {
      navigator.mediaDevices
        .getUserMedia({ video: true })
        .then((stream) => {
          video.style.display = "block";
          video.srcObject = stream;
          const track = stream.getVideoTracks()[0];
          const imageCapture = new ImageCapture(track);

          intervalId = setInterval(() => {
            imageCapture.grabFrame().then((bitmap) => {
              const canvas = document.createElement("canvas");
              canvas.width = bitmap.width;
              canvas.height = bitmap.height;
              const ctx = canvas.getContext("2d");
              ctx.drawImage(bitmap, 0, 0);
              canvas.toBlob((blob) => {
                const formData = new FormData();
                formData.append("frame", blob, "frame.jpg");

                fetch("/upload-frame", {
                  method: "POST",
                  body: formData,
                })
                  .then((res) => res.json())
                  .then((data) => {
                    sampleCount++;
                    sampleCounter.style.display = "block";
                    sampleCountSpan.textContent = sampleCount;
                    if (data.done) {
                      clearInterval(intervalId);
                      alert("Face data collection complete!");
                    }
                  });
              }, "image/jpeg");
            });
          }, 300);
        })
        .catch((err) => {
          console.error("Camera access error:", err);
          alert("Unable to access the camera. Please allow permissions.");
        });
    } else if (result.error) {
      // Handle authentication and other errors
      if (res.status === 409) {
        alert("A user with this email already exists. Please use a different email or log in.");
      } else if (res.status === 401) {
        alert("Authentication failed. Please check your email and password (DOB).");
      } else {
        alert(`Error: ${result.error}`);
      }
    }
  });
}
