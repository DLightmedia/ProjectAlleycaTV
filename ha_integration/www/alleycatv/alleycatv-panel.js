/**
 * AlleycaTV Panel
 * Home Assistant custom panel for controlling the AlleycaTV video distribution system.
 *
 * Place this file at:
 *   config/www/alleycatv/alleycatv-panel.js
 *
 * Register in configuration.yaml — see docs/setup.md
 */

class AlleycaTVPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._devices = {};       // pi_id → device object
    this._zones = {};         // zone_id → { name, pis: [] }
    this._selectedZone = null;
    this._eventUnsubscribe = null;
    this._serverUrl = null;
    this._contentFiles = [];
    this._initialized = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      // Resolve server URL from config entry options if available
      this._serverUrl = this._resolveServerUrl();
      this._render();
      this._initAsync();
    }
  }

  connectedCallback() {
    if (this._hass && !this._initialized) {
      this._initialized = true;
      this._serverUrl = this._resolveServerUrl();
      this._render();
      this._initAsync();
    }
  }

  disconnectedCallback() {
    if (this._eventUnsubscribe) {
      this._eventUnsubscribe();
      this._eventUnsubscribe = null;
    }
    this._initialized = false;
  }

  _resolveServerUrl() {
    // 1. Check panel element attribute set via configuration.yaml panel_custom config
    if (this._panel?.config?.server_url) return this._panel.config.server_url;
    // 2. Check hass panel config
    try {
      if (this.panel?.config?.server_url) return this.panel.config.server_url;
    } catch (_) {}
    // 3. Try config entry data
    try {
      const entry = Object.values(this._hass.config_entries || {})
        .find(e => e.domain === "alleycatv");
      if (entry?.data?.server_url) return entry.data.server_url;
    } catch (_) {}
    return "http://192.168.1.144"; // fallback — update this to match your server IP
  }

  async _initAsync() {
    await this._loadDevices();
    await this._subscribeToEvents();
    await this._loadContent();
    await this._fetchServerZones();
    this._buildZones();
    this._renderZoneList();
  }

  // ── Server API helpers ────────────────────────────────────────────────────────

  async _apiGet(path) {
    const resp = await fetch(`${this._serverUrl}${path}`);
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
    return resp.json();
  }

  async _apiPost(path, body) {
    const resp = await fetch(`${this._serverUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
    return resp.json();
  }

  async _apiDelete(path) {
    const resp = await fetch(`${this._serverUrl}${path}`, { method: "DELETE" });
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
    return resp.json();
  }

  // ── Data loading ─────────────────────────────────────────────────────────────

  async _loadDevices() {
    if (!this._hass) return;
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: "alleycatv/list_devices",
      });
      (result.devices || []).forEach(d => {
        this._devices[d.pi_id] = d;
      });
      console.info("[AlleycaTV] Loaded", Object.keys(this._devices).length, "device(s)");
    } catch (err) {
      console.warn("[AlleycaTV] Could not load device list:", err);
    }
  }

  async _subscribeToEvents() {
    if (!this._hass || this._eventUnsubscribe) return;
    try {
      this._eventUnsubscribe = await this._hass.connection.subscribeEvents(
        (event) => {
          const d = event.data;
          if (!d || !d.pi_id) return;
          this._devices[d.pi_id] = { ...this._devices[d.pi_id], ...d };
          this._buildZones();
          this._renderZoneList();
          if (this._selectedZone) this._renderZoneDetail(this._selectedZone);
        },
        "alleycatv_device_update"
      );
    } catch (err) {
      console.warn("[AlleycaTV] Could not subscribe to events:", err);
    }
  }

  async _fetchServerZones() {
    try {
      const zones = await this._apiGet("/api/zones");
      zones.forEach(z => {
        if (!this._serverZones) this._serverZones = {};
        this._serverZones[z.zone_id] = z;
      });
      console.info("[AlleycaTV] Loaded", zones.length, "server zone(s)");
    } catch (err) {
      console.warn("[AlleycaTV] Could not fetch server zones:", err);
    }
  }

  async _loadContent() {
    try {
      const resp = await fetch(`${this._serverUrl}/api/content/?base_url=${encodeURIComponent(this._serverUrl)}`);
      if (resp.ok) {
        this._contentFiles = await resp.json();
        this._populateFilePicker();
        console.info("[AlleycaTV] Loaded", this._contentFiles.length, "content files");
      }
    } catch (err) {
      console.warn("[AlleycaTV] Could not load content from server:", err);
    }
  }

  _buildZones() {
    const zones = {};
    // Seed from server-defined zones first so they show even without Pis
    Object.values(this._serverZones || {}).forEach(z => {
      zones[z.zone_id] = { zone_id: z.zone_id, name: z.name, pis: [] };
    });
    // Overlay Pi device reports
    Object.values(this._devices).forEach(d => {
      const z = d.zone || "unassigned";
      if (!zones[z]) zones[z] = { zone_id: z, pis: [] };
      const existing = zones[z].pis.findIndex(p => p.pi_id === d.pi_id);
      if (existing >= 0) zones[z].pis[existing] = d;
      else zones[z].pis.push(d);
    });
    this._zones = zones;
  }

  async _createZone(zoneId, zoneName) {
    try {
      await this._apiPost("/api/zones", { zone_id: zoneId, name: zoneName || zoneId });
      if (!this._serverZones) this._serverZones = {};
      this._serverZones[zoneId] = { zone_id: zoneId, name: zoneName || zoneId };
      this._buildZones();
      this._renderZoneList();
      this._showFeedback(`Zone "${zoneId}" created`, "success");
    } catch (err) {
      this._showFeedback(`Failed to create zone: ${err.message}`, "error");
    }
  }

  async _deleteZone(zoneId) {
    if (!confirm(`Delete zone "${zoneId}"? This cannot be undone.`)) return;
    try {
      await this._apiDelete(`/api/zones/${encodeURIComponent(zoneId)}`);
      delete this._serverZones?.[zoneId];
      delete this._zones[zoneId];
      if (this._selectedZone === zoneId) {
        this._selectedZone = null;
        this.shadowRoot.getElementById("zone-detail").style.display = "none";
        this.shadowRoot.getElementById("main-placeholder").style.display = "block";
      }
      this._renderZoneList();
      this._showFeedback(`Zone "${zoneId}" deleted`, "success");
    } catch (err) {
      this._showFeedback(`Failed to delete zone: ${err.message}`, "error");
    }
  }

  // ── Service calls ─────────────────────────────────────────────────────────────

  async _callService(service, data) {
    if (!this._hass) return;
    try {
      await this._hass.callService("alleycatv", service, data);
      this._showFeedback(`✓ ${service.replace(/_/g, " ")}`, "success");
    } catch (err) {
      this._showFeedback(`✗ ${err.message}`, "error");
    }
  }

  _playZone(zone_id) {
    this._callService("play_zone", { zone_id });
  }

  _stopZone(zone_id) {
    this._callService("stop_zone", { zone_id });
  }

  _interruptZone(zone_id) {
    const url = this._buildInterruptUrl(this._getSelectedFileUrl(), "file-picker");
    if (!url) return this._showFeedback("Select an announcement file first", "warn");
    this._callService("interrupt_zone", { zone_id, file_url: url });
  }

  _interruptPi(pi_id) {
    const url = this._buildInterruptUrl(this._getSelectedFileUrl(), "file-picker");
    if (!url) return this._showFeedback("Select an announcement file first", "warn");
    this._callService("interrupt_pi", { pi_id, file_url: url });
  }

  _reloadPlaylist(zone_id) {
    this._callService("reload_playlist", { zone_id });
  }

  _setVolume(zone_id, volume) {
    this._callService("set_volume_zone", { zone_id, volume: parseInt(volume) });
  }

  // ── Content picker helpers ────────────────────────────────────────────────────

  _getSelectedFileUrl() {
    const sel = this.shadowRoot.getElementById("file-picker");
    return sel ? sel.value : "";
  }

  _announcementItems() {
    return this._contentFiles.filter(f =>
      f.media_type === "announcement" ||
      (f.media_type === "webpage" && f.entry_id)
    );
  }

  _isVideoAnnouncementUrl(url) {
    const path = (url || "").split("?")[0].split("#")[0].toLowerCase();
    return /\.(mp4|mkv|avi|mov)$/.test(path);
  }

  _announcementOptionValue(f) {
    return (f.url || "").split("#")[0];
  }

  _getInterruptDurationPicker(pickerId) {
    const sel = this.shadowRoot.getElementById(`${pickerId}-duration`);
    return sel ? sel.value : "30";
  }

  _buildInterruptUrl(baseUrl, pickerId = "file-picker") {
    if (!baseUrl) return "";
    let url = baseUrl.split("#")[0];
    const mode = this._getInterruptDurationPicker(pickerId);

    if (this._isVideoAnnouncementUrl(url)) {
      if (mode === "hold") return `${url}#acv_hold=1`;
      return url;
    }
    if (mode === "hold") return `${url}#acv_hold=1`;
    if (mode === "custom") {
      const sec = parseInt(prompt("Display duration (seconds):", "30") || "30", 10);
      return `${url}#acv_duration=${sec > 0 ? sec : 30}`;
    }
    return `${url}#acv_duration=${mode}`;
  }

  _interruptDurationOptions() {
    return `
      <option value="30">30 seconds (default)</option>
      <option value="15">15 seconds</option>
      <option value="60">60 seconds</option>
      <option value="90">90 seconds</option>
      <option value="custom">Custom…</option>
      <option value="hold">Until stopped (Play/Stop)</option>`;
  }

  _populateFilePicker() {
    const announcements = this._announcementItems();
    const options = `<option value="">-- select announcement --</option>` +
      announcements.map(f =>
        `<option value="${this._announcementOptionValue(f)}">${f.filename}</option>`
      ).join("");
    ["file-picker", "file-picker-global"].forEach(id => {
      const sel = this.shadowRoot.getElementById(id);
      if (sel) sel.innerHTML = options;
    });
  }

  // ── Feedback ───────────────────────────────────────────────────────────────────

  _showFeedback(msg, type = "info") {
    const el = this.shadowRoot.getElementById("feedback");
    if (!el) return;
    const colors = { success: "#1d9e75", error: "#e24b4a", warn: "#ef9f27", info: "#378add" };
    el.textContent = msg;
    el.style.color = colors[type] || colors.info;
    el.style.opacity = "1";
    clearTimeout(this._feedbackTimer);
    this._feedbackTimer = setTimeout(() => { el.style.opacity = "0"; }, 3500);
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  _renderZoneList() {
    const container = this.shadowRoot.getElementById("zone-list");
    if (!container) return;
    const zoneIds = Object.keys(this._zones);
    if (zoneIds.length === 0) {
      container.innerHTML = `<p class="empty-hint">Waiting for Pi devices to report in…<br><span>Pis publish to <code>alleycatv/pi/{id}/status</code></span></p>`;
      return;
    }
    container.innerHTML = zoneIds.map(zid => {
      const z = this._zones[zid];
      const total = z.pis.length;
      const onlineCount = z.pis.filter(p => p.online !== false).length;
      const allPlaying = total > 0 && z.pis.every(p => p.state === "playing");
      const isEmpty = total === 0;
      const dotClass = allPlaying ? "playing" : onlineCount > 0 ? "online" : "offline";
      const subLabel = isEmpty ? "no devices" : `${onlineCount}/${total} online`;
      return `
        <div class="zone-chip ${this._selectedZone === zid ? "active" : ""} ${isEmpty ? "zone-empty" : ""}" data-zone="${zid}">
          <span class="zone-dot ${isEmpty ? "empty" : dotClass}"></span>
          <div class="zone-info">
            <span class="zone-name">${z.name || zid}</span>
            <span class="zone-sub">${subLabel}</span>
          </div>
        </div>`;
    }).join("");
    container.querySelectorAll(".zone-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        this._selectedZone = chip.dataset.zone;
        this._renderZoneList();
        this._renderZoneDetail(chip.dataset.zone);
        this.shadowRoot.getElementById("main-placeholder").style.display = "none";
        this.shadowRoot.getElementById("zone-detail").style.display = "block";
      });
    });
  }

  _renderZoneDetail(zone_id) {
    const detail = this.shadowRoot.getElementById("zone-detail");
    if (!detail) return;
    const zone = this._zones[zone_id];
    if (!zone) return;

    const serverZone = (this._serverZones || {})[zone_id];
    detail.querySelector("#zone-title").textContent = serverZone?.name || zone_id;

    const playingPis = (zone.pis || []).filter(p => p.online !== false && p.state === "playing");
    const summaryPi = playingPis[0] || (zone.pis || []).find(p => p.online !== false);
    const nowEl = detail.querySelector("#now-playing-summary");
    if (nowEl) {
      if (summaryPi && summaryPi.current_file) {
        nowEl.innerHTML = `
          <div class="playback-row"><span class="playback-label">Now Playing</span><span class="playback-value">${summaryPi.current_file}</span></div>
          <div class="playback-row"><span class="playback-label">Up Next</span><span class="playback-value">${summaryPi.next_file || "—"}</span></div>`;
      } else {
        nowEl.innerHTML = `<p class="playback-idle">${summaryPi ? "Nothing playing" : "No devices online in this zone"}</p>`;
      }
    }

    const pis = this.shadowRoot.getElementById("pi-cards");
    if (!pis) return;
    pis.innerHTML = (zone.pis || []).map(d => {
      const online  = d.online !== false;
      const stateLabel = d.state || "unknown";
      const stateClass = stateLabel === "playing" ? "state-playing"
                       : stateLabel === "interrupted" ? "state-interrupted"
                       : "state-stopped";
      return `
        <div class="pi-card ${online ? "" : "pi-offline"}">
          <div class="pi-header">
            <span class="status-dot ${online ? "online" : "offline"}"></span>
            <strong>${d.pi_id}</strong>
            <span class="pi-state ${stateClass}">${stateLabel}</span>
          </div>
          <div class="pi-meta">
            ${d.ip ? `<span>IP: ${d.ip}</span>` : ""}
            ${d.current_file ? `<span><strong>Now:</strong> ${d.current_file}</span>` : ""}
            ${d.next_file ? `<span><strong>Next:</strong> ${d.next_file}</span>` : ""}
          </div>
          <div class="pi-actions">
            <button class="btn btn-sm btn-warning pi-interrupt" data-pi="${d.pi_id}" title="Play an announcement on this display">Interrupt</button>
          </div>
        </div>`;
    }).join("");

    pis.querySelectorAll(".pi-interrupt").forEach(btn => {
      btn.addEventListener("click", () => this._interruptPi(btn.dataset.pi));
    });

    // Update volume display
    const volInput = this.shadowRoot.getElementById("vol-slider");
    if (volInput) {
      volInput.dataset.zone = zone_id;
    }
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: var(--primary-font-family, sans-serif);
          background: var(--primary-background-color, #f5f5f5);
          min-height: 100vh;
          color: var(--primary-text-color, #212121);
        }
        .page-header {
          background: var(--card-background-color, #fff);
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          padding: 16px 24px;
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .page-header h1 { margin: 0; font-size: 20px; font-weight: 500; }
        .page-header .subtitle { font-size: 13px; color: var(--secondary-text-color, #727272); margin: 0; }
        .brand-icon {
          width: 36px; height: 36px;
          background: linear-gradient(135deg, #1d5fa8, #1d9e75);
          border-radius: 8px;
          display: flex; align-items: center; justify-content: center;
        }
        .brand-icon svg { width: 22px; height: 22px; fill: #fff; }
        #feedback {
          font-size: 13px; font-weight: 500;
          transition: opacity 0.5s; min-height: 20px; margin-left: auto;
        }

        .layout {
          display: grid;
          grid-template-columns: 260px 1fr;
          height: calc(100vh - 70px);
        }

        /* ── Sidebar ── */
        .sidebar {
          background: var(--card-background-color, #fff);
          border-right: 1px solid var(--divider-color, #e0e0e0);
          overflow-y: auto;
          padding: 16px;
        }
        .sidebar-header {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 12px;
        }
        .sidebar-title {
          font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
          text-transform: uppercase; color: var(--secondary-text-color, #727272);
          margin: 0;
        }
        .btn-icon {
          width: 26px; height: 26px; border-radius: 6px; border: none;
          background: #1d5fa8; color: #fff; font-size: 18px; line-height: 1;
          cursor: pointer; display: flex; align-items: center; justify-content: center;
          padding: 0;
        }
        .btn-icon:hover { opacity: 0.85; }
        #new-zone-form input {
          width: 100%; padding: 8px 10px; border-radius: 6px;
          border: 1px solid var(--divider-color, #e0e0e0);
          font-size: 13px; font-family: inherit;
          background: var(--primary-background-color, #fff);
          color: var(--primary-text-color, #212121);
          box-sizing: border-box; display: block;
        }
        #zone-list { display: flex; flex-direction: column; gap: 6px; }
        .zone-chip {
          display: flex; align-items: center; gap: 10px;
          padding: 10px 12px; border-radius: 8px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-left: 3px solid transparent;
          cursor: pointer; transition: border-color 0.15s;
          background: var(--secondary-background-color, #f5f5f5);
        }
        .zone-chip:hover { border-left-color: var(--secondary-text-color, #727272); }
        .zone-chip.active {
          border-color: var(--divider-color, #e0e0e0);
          border-left: 3px solid #1d5fa8;
          background: var(--secondary-background-color, #f5f5f5);
        }
        .zone-chip.active .zone-name { font-weight: 600; color: var(--primary-text-color, #212121); }
        .zone-dot {
          width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
        }
        .zone-dot.playing { background: #1d9e75; }
        .zone-dot.online  { background: #ef9f27; }
        .zone-dot.offline { background: #9e9e9e; }
        .zone-dot.empty   { background: transparent; border: 2px solid #9e9e9e; }
        .zone-chip.zone-empty { opacity: 0.5; }
        .zone-chip.zone-empty:hover { opacity: 0.75; }
        .zone-info { display: flex; flex-direction: column; }
        .zone-name { font-size: 14px; font-weight: 500; }
        .zone-sub  { font-size: 11px; color: var(--secondary-text-color, #727272); }
        .empty-hint {
          font-size: 13px; color: var(--secondary-text-color, #727272);
          text-align: center; padding: 32px 8px; line-height: 1.6;
        }
        .empty-hint code {
          background: var(--secondary-background-color, #f0f0f0);
          padding: 2px 6px; border-radius: 4px; font-size: 12px;
        }

        /* ── Main area ── */
        .main { padding: 24px; overflow-y: auto; }

        /* ── Placeholder ── */
        #main-placeholder { text-align: center; padding: 80px 32px; color: var(--secondary-text-color, #727272); }
        #main-placeholder svg { opacity: 0.2; margin-bottom: 16px; }

        /* ── Zone detail ── */
        #zone-detail { display: none; }
        .zone-detail-header {
          display: flex; align-items: center; gap: 16px; margin-bottom: 20px; flex-wrap: wrap;
        }
        .zone-detail-header h2 { margin: 0; font-size: 18px; font-weight: 500; flex: 1; }
        .now-playing-box {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 12px; padding: 16px 20px; margin-bottom: 16px;
        }
        .playback-row { display: flex; gap: 12px; margin-bottom: 8px; font-size: 14px; }
        .playback-row:last-child { margin-bottom: 0; }
        .playback-label { min-width: 90px; color: var(--secondary-text-color, #727272); font-weight: 500; }
        .playback-value { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .playback-idle { margin: 0; color: var(--secondary-text-color, #727272); font-size: 13px; }

        /* ── Cards ── */
        .card {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 12px; padding: 20px; margin-bottom: 16px;
        }
        .card-title {
          font-size: 11px; font-weight: 600; letter-spacing: 0.06em;
          text-transform: uppercase; color: var(--secondary-text-color, #727272);
          margin: 0 0 16px;
        }

        /* ── Zone controls ── */
        .zone-controls { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }
        label { display: block; font-size: 13px; margin-bottom: 4px; color: var(--secondary-text-color, #727272); }
        select, input[type="range"] {
          width: 100%; padding: 9px 12px;
          border: 1px solid var(--divider-color, #e0e0e0); border-radius: 8px;
          font-size: 14px; font-family: inherit;
          background: var(--primary-background-color, #fff);
          color: var(--primary-text-color, #212121); box-sizing: border-box;
        }
        input[type="range"] { padding: 4px 0; accent-color: #1d5fa8; }
        .slider-row { display: flex; align-items: center; gap: 10px; }
        .slider-row input { flex: 1; }
        .slider-val { min-width: 36px; text-align: right; font-size: 13px; font-weight: 500; }

        /* ── Pi cards ── */
        #pi-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
        .pi-card {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0); border-radius: 10px; padding: 14px;
        }
        .pi-card.pi-offline { opacity: 0.55; }
        .pi-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
        .pi-header strong { flex: 1; font-size: 14px; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .status-dot.online  { background: #1d9e75; }
        .status-dot.offline { background: #e24b4a; }
        .pi-state { font-size: 11px; padding: 2px 7px; border-radius: 10px; font-weight: 500; }
        .state-playing     { background: #e1f5ee; color: #0f6e56; }
        .state-interrupted { background: #fff3e0; color: #e65100; }
        .state-stopped     { background: #f5f5f5; color: #757575; }
        .pi-meta { font-size: 12px; color: var(--secondary-text-color, #727272); margin-bottom: 10px; display: flex; flex-direction: column; gap: 2px; }
        .pi-meta span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .pi-actions { display: flex; gap: 6px; }

        /* ── Buttons ── */
        .btn {
          padding: 9px 18px; border-radius: 8px; border: none; cursor: pointer;
          font-size: 14px; font-weight: 500; font-family: inherit;
          transition: opacity 0.15s, transform 0.1s;
        }
        .btn:hover { opacity: 0.85; }
        .btn:active { transform: scale(0.97); }
        .btn-primary  { background: #1d5fa8; color: #fff; }
        .btn-success  { background: #1d9e75; color: #fff; }
        .btn-danger   { background: #e24b4a; color: #fff; }
        .btn-warning  { background: #ef9f27; color: #fff; }
        .btn-secondary { background: var(--secondary-background-color, #f0f0f0); color: var(--primary-text-color, #212121); }
        .btn-sm { padding: 6px 12px; font-size: 12px; }

        /* ── Broadcast banner ── */
        .broadcast-card {
          background: linear-gradient(135deg, #0d3a6e, #1d5fa8);
          border-radius: 12px; padding: 20px; color: #fff; margin-bottom: 20px;
        }
        .broadcast-card h3 { margin: 0 0 4px; font-size: 15px; font-weight: 500; }
        .broadcast-card p  { margin: 0 0 12px; font-size: 13px; opacity: 0.8; }
      </style>

      <div class="page-header">
        <div class="brand-icon">
          <svg viewBox="0 0 24 24"><path d="M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14zM10 8l6 4-6 4V8z"/></svg>
        </div>
        <div>
          <h1>AlleycaTV</h1>
          <p class="subtitle">Zone video distribution</p>
        </div>
        <span id="feedback"></span>
      </div>

      <div class="layout">
        <aside class="sidebar">
          <div class="sidebar-header">
            <p class="sidebar-title">Zones</p>
            <button class="btn-icon" id="btn-new-zone" title="Create zone">+</button>
          </div>
          <div id="new-zone-form" style="display:none;margin-bottom:12px;">
            <input id="new-zone-id" type="text" placeholder="Zone ID (e.g. zone-lobby)" style="margin-bottom:6px;" />
            <input id="new-zone-name" type="text" placeholder="Display name (optional)" style="margin-bottom:8px;" />
            <div style="display:flex;gap:6px;">
              <button class="btn btn-primary btn-sm" id="btn-zone-save" style="flex:1">Create</button>
              <button class="btn btn-secondary btn-sm" id="btn-zone-cancel">Cancel</button>
            </div>
          </div>
          <div id="zone-list"><p class="empty-hint">Waiting for devices…</p></div>
        </aside>

        <main class="main">
          <!-- Placeholder before zone selected -->
          <div id="main-placeholder">
            <div class="broadcast-card">
              <h3>Broadcast Interrupt to All Zones</h3>
              <p>Play an announcement on every connected Pi simultaneously.</p>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                <select id="file-picker-global" style="flex:1;min-width:200px;background:rgba(255,255,255,0.15);color:#fff;border-color:rgba(255,255,255,0.3)">
                  <option value="">-- select announcement --</option>
                </select>
                <select id="file-picker-global-duration" style="min-width:180px;background:rgba(255,255,255,0.15);color:#fff;border-color:rgba(255,255,255,0.3)">
                  ${this._interruptDurationOptions()}
                </select>
                <button class="btn btn-sm" style="background:rgba(255,255,255,0.2);color:#fff;border:1px solid rgba(255,255,255,0.3);" id="bcast-interrupt">
                  Interrupt All
                </button>
              </div>
            </div>
            <svg width="64" height="64" viewBox="0 0 24 24" fill="currentColor">
              <path d="M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14zM10 8l6 4-6 4V8z"/>
            </svg>
            <p>Select a zone from the sidebar to manage it.</p>
          </div>

          <!-- Per-zone detail panel -->
          <div id="zone-detail">
            <div class="zone-detail-header">
              <h2 id="zone-title">—</h2>
              <div class="zone-controls">
                <button class="btn btn-success" id="btn-play" title="Resume playlist playback">▶ Play</button>
                <button class="btn btn-danger"  id="btn-stop" title="Stop playback on all displays in this zone">■ Stop</button>
                <button class="btn btn-warning" id="btn-reload" title="Reload playlist from server">↺ Reload</button>
                <button class="btn btn-secondary" id="btn-delete-zone" style="margin-left:8px;color:#e24b4a;">🗑 Delete Zone</button>
              </div>
            </div>

            <div class="now-playing-box" id="now-playing-summary">
              <p class="playback-idle">Select a zone to see playback status</p>
            </div>

            <!-- Interrupt card -->
            <div class="card">
              <p class="card-title">Interrupt Announcement</p>
              <label>Announcement</label>
              <select id="file-picker">
                <option value="">-- loading… --</option>
              </select>
              <label style="margin-top:10px;display:block">Display duration</label>
              <select id="file-picker-duration">
                ${this._interruptDurationOptions()}
              </select>
              <p style="font-size:12px;color:var(--secondary-text-color,#888);margin-top:8px;line-height:1.4">
                Photos and scoreboards use the duration above (default 30s). Videos play in full.
                “Until stopped” stays on screen until you press Play or Stop.
              </p>
              <div style="margin-top:12px">
                <button class="btn btn-warning" id="btn-interrupt">⚡ Interrupt Zone</button>
              </div>
            </div>

            <!-- Volume card -->
            <div class="card">
              <p class="card-title">Volume</p>
              <div class="slider-row">
                <input type="range" id="vol-slider" min="0" max="100" value="80" data-zone=""
                  oninput="this.parentElement.querySelector('.slider-val').textContent=this.value+'%'" />
                <span class="slider-val">80%</span>
              </div>
              <div style="margin-top:12px">
                <button class="btn btn-secondary" id="btn-vol">Set Volume</button>
              </div>
            </div>

            <!-- Pi status cards -->
            <div class="card">
              <p class="card-title">Displays in this Zone</p>
              <div id="pi-cards"></div>
            </div>
          </div>
        </main>
      </div>
    `;

    this._attachEventListeners();
  }

  _attachEventListeners() {
    const root = this.shadowRoot;

    // Zone detail controls
    root.getElementById("btn-play")?.addEventListener("click", () => {
      if (this._selectedZone) this._playZone(this._selectedZone);
    });
    root.getElementById("btn-stop")?.addEventListener("click", () => {
      if (this._selectedZone) this._stopZone(this._selectedZone);
    });
    root.getElementById("btn-reload")?.addEventListener("click", () => {
      if (this._selectedZone) this._reloadPlaylist(this._selectedZone);
    });
    root.getElementById("btn-interrupt")?.addEventListener("click", () => {
      if (this._selectedZone) this._interruptZone(this._selectedZone);
    });
    root.getElementById("btn-vol")?.addEventListener("click", () => {
      const slider = root.getElementById("vol-slider");
      if (this._selectedZone && slider) this._setVolume(this._selectedZone, slider.value);
    });

    // New zone form
    root.getElementById("btn-new-zone")?.addEventListener("click", () => {
      const form = root.getElementById("new-zone-form");
      form.style.display = form.style.display === "none" ? "block" : "none";
      if (form.style.display === "block") root.getElementById("new-zone-id")?.focus();
    });
    root.getElementById("btn-zone-cancel")?.addEventListener("click", () => {
      root.getElementById("new-zone-form").style.display = "none";
      root.getElementById("new-zone-id").value = "";
      root.getElementById("new-zone-name").value = "";
    });
    root.getElementById("btn-zone-save")?.addEventListener("click", () => {
      const id = root.getElementById("new-zone-id").value.trim();
      const name = root.getElementById("new-zone-name").value.trim();
      if (!id) return this._showFeedback("Zone ID is required", "warn");
      root.getElementById("new-zone-form").style.display = "none";
      root.getElementById("new-zone-id").value = "";
      root.getElementById("new-zone-name").value = "";
      this._createZone(id, name);
    });

    // Delete zone
    root.getElementById("btn-delete-zone")?.addEventListener("click", () => {
      if (this._selectedZone) this._deleteZone(this._selectedZone);
    });

    // Broadcast interrupt
    root.getElementById("bcast-interrupt")?.addEventListener("click", () => {
      const sel = root.getElementById("file-picker-global");
      const url = this._buildInterruptUrl(sel ? sel.value : "", "file-picker-global");
      if (!url) return this._showFeedback("Select an announcement file", "warn");
      Object.keys(this._zones).forEach(zid => {
        this._hass?.callService("alleycatv", "interrupt_zone", { zone_id: zid, file_url: url });
      });
      this._showFeedback("Broadcast interrupt sent to all zones", "success");
    });
  }
}

customElements.define("alleycatv-panel", AlleycaTVPanel);
