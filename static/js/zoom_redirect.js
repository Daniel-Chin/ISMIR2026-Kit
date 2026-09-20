(function () {
  const PREF_KEY = "zoom_redirect_pref";
  const TOKEN_COOKIE = "zoom_redirect_token";
  const AUTO_REDIRECT_SECONDS = 3;

  const targetsElement = document.getElementById("zoom-targets");
  const configElement = document.getElementById("zoom-config");
  const titleElement = document.getElementById("zoom-room-title");
  const metaElement = document.getElementById("zoom-room-meta");
  const statusElement = document.getElementById("zoom-status");
  const countdownRowElement = document.getElementById("zoom-countdown-row");
  const countdownElement = document.getElementById("zoom-countdown");
  const pauseCountdownButton = document.getElementById("zoom-pause-countdown");
  const checkboxElement = document.getElementById("zoom-save-checkbox");
  const joinButton = document.getElementById("zoom-join-button");
  const slackHelpElement = document.getElementById("zoom-slack-help");
  const slackHelpTextElement = document.getElementById("zoom-slack-help-text");
  const slackHelpLinkElement = document.getElementById("zoom-slack-help-link");
  const checkboxContainer = checkboxElement.closest(".form-check");

  if (!targetsElement || !configElement || !titleElement || !metaElement || !statusElement || !countdownRowElement || !countdownElement || !pauseCountdownButton || !checkboxElement || !joinButton || !slackHelpElement || !slackHelpTextElement || !slackHelpLinkElement) {
    return;
  }

  let countdownIntervalId = null;
  let countdownRemaining = AUTO_REDIRECT_SECONDS;
  let activeCountdownRoom = null;
  let activeCountdownPasscode = false;

  const eventUid = new URLSearchParams(window.location.search).get("event_uid") || "";
  const urlToken = new URLSearchParams(window.location.search).get("token") || "";

  const parsedTargets = JSON.parse(targetsElement.textContent || "{}");
  const zoomConfig = JSON.parse(configElement.textContent || "{}");
  const accessToken = String(zoomConfig.access_token || "");
  const room = parsedTargets[eventUid];

  function showSlackPrompt(targetRoom) {
    const hasChannelLink = Boolean(targetRoom.channel_url);
    const channelLabel = targetRoom.slack_channel ? ` (${targetRoom.slack_channel})` : "";
    slackHelpTextElement.textContent = "To save credentials for automatic passcode access next time, join Zoom from the Slack channel.";
    if (hasChannelLink) {
      slackHelpLinkElement.href = targetRoom.channel_url;
      slackHelpLinkElement.classList.remove("d-none");
    } else {
      slackHelpLinkElement.classList.add("d-none");
    }
    slackHelpElement.classList.remove("d-none");
  }

  function validToken(token) {
    return Boolean(token) && token === accessToken;
  }

  function getCookie(name) {
    const prefix = `${name}=`;
    const parts = document.cookie ? document.cookie.split("; ") : [];
    for (const part of parts) {
      if (part.startsWith(prefix)) {
        return decodeURIComponent(part.slice(prefix.length));
      }
    }
    return "";
  }

  function setCookie(name, value) {
    const encodedValue = encodeURIComponent(value);
    document.cookie = `${name}=${encodedValue}; path=/; max-age=31536000; samesite=lax`;
  }

  function removeCookie(name) {
    document.cookie = `${name}=; path=/; max-age=0; samesite=lax`;
  }

  function getSavedPreference() {
    try {
      return window.localStorage.getItem(PREF_KEY) || "INITIAL";
    } catch (error) {
      return "INITIAL";
    }
  }

  function setSavedPreference(value) {
    try {
      window.localStorage.setItem(PREF_KEY, value);
    } catch (error) {
      return;
    }
  }

  function stripPasscode(joinUrl) {
    try {
      const parsed = new URL(joinUrl, window.location.href);
      parsed.searchParams.delete("pwd");
      return parsed.toString();
    } catch (error) {
      return joinUrl;
    }
  }

  function resolveRoom() {
    if (!room || !room.join_url) {
      titleElement.textContent = "Room not found";
      metaElement.textContent = `Unknown event UID: ${eventUid || "(missing)"}`;
      statusElement.textContent = "The utility link did not contain a valid room reference.";
      checkboxElement.disabled = true;
      joinButton.disabled = true;
      return null;
    }

    titleElement.textContent = room.title || "Zoom room";
    metaElement.textContent = `Room ID: ${room.uid}`;
    return room;
  }

  function immediateToken() {
    const savedToken = getCookie(TOKEN_COOKIE);
    if (validToken(urlToken)) {
      return urlToken;
    }
    if (validToken(savedToken)) {
      return savedToken;
    }
    return "";
  }

  function hasValidAccess() {
    return Boolean(immediateToken());
  }

  function autoToken(state) {
    if (state === "NO") {
      return "";
    }
    const savedToken = getCookie(TOKEN_COOKIE);
    if (validToken(urlToken)) {
      return urlToken;
    }
    if (validToken(savedToken)) {
      return savedToken;
    }
    return "";
  }

  function redirectTo(targetRoom, includePasscode) {
    const destination = includePasscode ? targetRoom.join_url : stripPasscode(targetRoom.join_url);
    window.location.replace(destination);
  }

  function renderCountdownText() {
    const includePasscode = activeCountdownPasscode;
    countdownElement.textContent = includePasscode
      ? `Redirecting to Zoom with saved credentials in ${countdownRemaining} seconds...`
      : `Redirecting to Zoom in ${countdownRemaining} seconds...`;
  }

  function stopCountdown() {
    if (countdownIntervalId !== null) {
      window.clearInterval(countdownIntervalId);
      countdownIntervalId = null;
    }
  }

  function showCountdown(state, targetRoom) {
    countdownRowElement.classList.remove("d-none");
    pauseCountdownButton.classList.remove("d-none");
    activeCountdownRoom = targetRoom;
    activeCountdownPasscode = state === "YES" && Boolean(autoToken(state));
    countdownRemaining = AUTO_REDIRECT_SECONDS;
    renderCountdownText();

    stopCountdown();
    countdownIntervalId = window.setInterval(() => {
      countdownRemaining -= 1;
      if (countdownRemaining <= 0) {
        stopCountdown();
        redirectTo(activeCountdownRoom, activeCountdownPasscode);
        return;
      }
      renderCountdownText();
    }, 1000);
  }

  pauseCountdownButton.addEventListener("click", () => {
    stopCountdown();
    countdownRowElement.classList.add("d-none");
    pauseCountdownButton.classList.add("d-none");
  });

  const targetRoom = resolveRoom();
  if (!targetRoom) {
    return;
  }

  if (!hasValidAccess()) {
    showSlackPrompt(targetRoom);
    if (checkboxContainer) {
      checkboxContainer.classList.add("d-none");
    }
  }

  const savedPreference = getSavedPreference();
  const initialCheckboxState = savedPreference === "NO" ? false : true;
  checkboxElement.checked = initialCheckboxState;

  if (!hasValidAccess()) {
    statusElement.textContent = "Access token missing or invalid. Join still works with manual passcode entry.";
  } else if (savedPreference === "YES") {
    statusElement.textContent = "Saved credentials detected. Redirecting automatically.";
    showCountdown("YES", targetRoom);
  } else if (savedPreference === "NO") {
    statusElement.textContent = "This browser is set to avoid saving credentials. Redirecting automatically.";
    showCountdown("NO", targetRoom);
  } else {
    statusElement.textContent = "No saved preference yet. Press the button to join or save credentials.";
  }

  joinButton.addEventListener("click", () => {
    const state = checkboxElement.checked ? "YES" : "NO";
    const token = immediateToken();
    setSavedPreference(state);

    if (state === "YES") {
      if (token) {
        setCookie(TOKEN_COOKIE, token);
      } else {
        removeCookie(TOKEN_COOKIE);
      }
    } else {
      removeCookie(TOKEN_COOKIE);
    }

    redirectTo(targetRoom, Boolean(token));
  });
})();