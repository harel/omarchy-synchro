import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: false
  property int page: 0
  property string cli: localPath(Qt.resolvedUrl("cli.sh"))
  property string action: ""
  property string message: "Ready"
  property bool actionFailed: false
  property string detail: ""
  property string repository: "Not selected"
  property string repoDraft: ""
  property string branch: "—"
  property string origin: ""
  property string originDraft: ""
  property string remoteState: "unconfigured"
  property string repoState: "uninitialized"
  property int dirty: 0
  property int snapshotPending: 0
  property int ahead: 0
  property int behind: 0
  property bool includeDevice: false
  property bool easterEggOpen: false
  property string commitMessage: "Update Omarchy configuration"
  property string confirmAction: ""

  readonly property color background: Color.menu.background
  readonly property color foreground: Color.menu.text
  readonly property color border: Color.menu.border
  readonly property color accent: Color.menu.selectedText
  readonly property color muted: Qt.darker(foreground, 1.55)
  readonly property color urgent: Color.urgent
  readonly property string fontFamily: Style.font.menuFamily
  readonly property var pages: [
    { title: "Overview", icon: "󰋜", subtitle: "Repository health" },
    { title: "Setup", icon: "󰒓", subtitle: "Repository and origin" },
    { title: "Snapshot", icon: "󰆓", subtitle: "Capture configuration" },
    { title: "Restore", icon: "󰁯", subtitle: "Preview and apply" },
    { title: "Seed", icon: "󰐕", subtitle: "New laptop plan" }
  ]

  function localPath(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0) value = value.substring(7)
    return decodeURIComponent(value)
  }

  function open(payloadJson) {
    opened = true
    page = 0
    message = "Refreshing repository status…"
    refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() { opened = false }

  function dismiss() {
    opened = false
    if (shell && typeof shell.hide === "function")
      shell.hide((manifest && manifest.id) || "harel.omarchy-synchro")
  }

  function run(nextAction, args) {
    if (process.running) return
    action = nextAction
    actionFailed = false
    message = "Working…"
    process.capturedStdout = ""
    process.capturedStderr = ""
    process.outputBytes = 0
    process.outputTruncated = false
    process.command = [cli, "--qml"].concat(args)
    process.running = true
  }

  function refresh() { run("overview", ["--json", "snapshot"]) }

  function fetchRemoteStatus() { run("status-fetch", ["--json", "status", "--fetch"]) }

  function showSeedHelp() {
    detail = [
      "CHECK\n  Verify the base Omarchy installation, selected repository, and snapshot schema.",
      "RESTORE\n  Preview portable configuration files that would change. Nothing is applied.",
      "PACKAGES\n  Compare declared native and AUR packages with what is installed.",
      "PLUGINS\n  Report installed, missing, and manual-source third-party Omarchy plugins.",
      "MIME\n  Compare saved MIME and default-application settings with this machine.",
      "RELOAD\n  Identify Shell, Hyprland, or terminal components that would need reloading.",
      "REPORT\n  List device-specific files, excluded secrets, and remaining manual steps."
    ].join("\n\n")
    actionFailed = false
    message = "Seed stage help"
  }

  function parse(raw) {
    try { return JSON.parse(String(raw || "{}")) }
    catch (error) { return null }
  }

  function applyStatus(data) {
    if (!data) return
    repository = String(data.repository || "Not selected")
    repoDraft = repository === "Not selected" ? "" : repository
    branch = String(data.branch || "—")
    origin = String(data.origin || "")
    originDraft = origin
    remoteState = String(data.remoteState || "unconfigured")
    repoState = String(data.state || "uninitialized")
    dirty = Number(data.dirtyFileCount !== undefined ? data.dirtyFileCount : (data.dirtyFiles || []).length)
    ahead = Number(data.ahead || 0)
    behind = Number(data.behind || 0)
  }

  function applyOverview(data) {
    if (!data) return
    snapshotPending = (data.changes || []).length
    applyStatus(data.repositoryStatus || data)
  }

  function friendlyOutput(data, raw) {
    if (!data) return raw || "No output"
    if (data.error) return String(data.error)
    if (data.commit) return "Committed managed snapshot changes.\n\n" + String(data.commit) + "\n" + String(data.message || "") + "\n\nNothing was pushed."
    if (data.pushed) return "Pushed branch " + String(data.pushed) + " to\n" + String(data.origin || "origin") + "."
    if (data.lines) return data.lines.join("\n\n")
    if (data.summary && data.repositoryStatus) {
      var snapshotLines = ["LIVE CONFIGURATION"]
      if (data.changes && data.changes.length) {
        snapshotLines.push(data.changes.length + " change" + (data.changes.length === 1 ? "" : "s") + " ready to capture:")
        for (var s = 0; s < data.changes.length; s++) snapshotLines.push("  " + String(data.changes[s]))
      } else snapshotLines.push("Captured snapshot is up to date.")

      var pending = data.repositoryStatus.dirtyFiles || []
      var pendingCount = Number(data.repositoryStatus.dirtyFileCount !== undefined ? data.repositoryStatus.dirtyFileCount : pending.length)
      snapshotLines.push("", "GIT REPOSITORY")
      if (pendingCount) {
        snapshotLines.push(pendingCount + " pending change" + (pendingCount === 1 ? "" : "s") + " awaiting review/commit:")
        for (var g = 0; g < pending.length; g++) snapshotLines.push("  " + String(pending[g]))
        if (pendingCount > pending.length) snapshotLines.push("  [" + (pendingCount - pending.length) + " more filenames omitted; use git status in the repository]")
      } else snapshotLines.push("Working tree is clean.")
      snapshotLines.push("", "Snapshot does not stage, commit, or push. Use the separately confirmed Git controls below.")
      return snapshotLines.join("\n")
    }
    if (data.changes) {
      if (data.changes.length === 0) return "No changes found."
      var lines = []
      for (var i = 0; i < data.changes.length; i++) {
        var item = data.changes[i]
        lines.push(typeof item === "string" ? item : String(item.scope || "portable") + "  " + String(item.destination || ""))
      }
      return lines.join("\n")
    }
    if (data.stages) {
      var stages = []
      for (var j = 0; j < data.stages.length; j++) stages.push((j + 1) + ". " + data.stages[j].name + " — " + data.stages[j].description)
      return stages.join("\n\n")
    }
    if (data.actions) {
      var actions = []
      for (var k = 0; k < data.actions.length; k++) {
        var plugin = data.actions[k]
        actions.push(String(plugin.state || "unknown").toUpperCase() + "  " + String(plugin.id || "")
          + (plugin.source ? "\n  " + String(plugin.source) : "\n  Manual source required"))
      }
      if (data.manual && data.manual.length) actions.push("MANUAL STEPS\n  " + data.manual.join("\n  "))
      return actions.length ? actions.join("\n\n") : "No third-party plugins declared."
    }
    return raw || "Action completed."
  }

  function requestConfirmation(kind) {
    confirmAction = kind
    if (kind === "snapshot") {
      confirmDialog.message = "Replace the managed snapshot with the previewed local configuration? No commit or push will occur."
      confirmDialog.confirmText = "Apply snapshot"
    } else if (kind === "restore") {
      confirmDialog.message = "Apply the previewed configuration to this laptop? Existing files will be backed up first."
      confirmDialog.confirmText = "Apply restore"
    } else if (kind === "commit") {
      confirmDialog.message = "Stage only Synchro-managed snapshot and policy paths, then commit them with this message?\n\n" + commitMessage
      confirmDialog.confirmText = "Commit snapshot"
    } else if (kind === "push") {
      confirmDialog.message = "Push committed configuration history to the configured origin? Uncommitted files will not be included."
      confirmDialog.confirmText = "Push commits"
    } else {
      confirmDialog.message = "Remove origin from the configuration repository? Files and commits will not be changed."
      confirmDialog.confirmText = "Remove origin"
    }
    confirmDialog.opened = true
  }

  function runConfirmed() {
    confirmDialog.opened = false
    if (confirmAction === "snapshot") run("snapshot-apply", ["--json", "snapshot", "--apply"])
    else if (confirmAction === "commit") run("repo-commit", ["--json", "repo", "commit", "--message", commitMessage.trim()])
    else if (confirmAction === "push") run("repo-push", ["--json", "repo", "push"])
    else if (confirmAction === "restore") {
      var restoreArgs = ["--json", "restore", "--apply"]
      if (includeDevice) restoreArgs.push("--include-device")
      run("restore-apply", restoreArgs)
    } else run("origin-remove", ["--json", "repo", "origin", "remove"])
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "harel-omarchy-synchro"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle { anchors.fill: parent; color: Color.menu.scrim }
    MouseArea { anchors.fill: parent; onClicked: root.dismiss() }

    BorderSurface {
      id: card
      width: Math.min(Style.space(980), panel.width - Style.space(48))
      height: Math.min(Style.space(650), panel.height - Style.space(48))
      anchors.centerIn: parent
      color: root.background
      borderSpec: Border.surfaceSpec("menu", "border", root.border, Math.max(1, Style.space(2)))
      radius: Style.cornerRadius
      padding: 0

      MouseArea { anchors.fill: parent; onClicked: {} }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: {
          if (root.easterEggOpen) root.easterEggOpen = false
          else root.dismiss()
        }

        RowLayout {
          anchors.fill: parent
          spacing: 0

          Rectangle {
            Layout.preferredWidth: Style.space(230)
            Layout.fillHeight: true
            color: Util.alpha(root.foreground, 0.035)

            Column {
              anchors.fill: parent
              anchors.margins: Style.space(18)
              spacing: Style.space(8)

              Row {
                height: Style.space(58)
                spacing: Style.space(12)
                Text { text: "󰓦"; color: root.accent; font.family: root.fontFamily; font.pixelSize: Style.font.display }
                Column {
                  anchors.verticalCenter: parent.verticalCenter
                  Text {
                    id: pluginName
                    text: "Omarchy Synchro"
                    color: nameMouse.containsMouse ? root.accent : root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.title
                    MouseArea {
                      id: nameMouse
                      anchors.fill: parent
                      anchors.margins: -Style.space(4)
                      hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: root.easterEggOpen = true
                    }
                  }
                  Text { text: "Private config manager"; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
                }
              }

              Item { width: 1; height: Style.space(8) }

              Repeater {
                model: root.pages
                Rectangle {
                  required property int index
                  required property var modelData
                  width: parent.width
                  height: Style.space(54)
                  radius: Style.cornerRadius
                  color: root.page === index ? Util.alpha(root.accent, 0.13) : (navMouse.containsMouse ? Util.alpha(root.foreground, 0.06) : "transparent")
                  border.color: root.page === index ? Util.alpha(root.accent, 0.5) : "transparent"
                  border.width: root.page === index ? 1 : 0

                  Row {
                    anchors.fill: parent
                    anchors.margins: Style.space(12)
                    spacing: Style.space(12)
                    Text { anchors.verticalCenter: parent.verticalCenter; text: modelData.icon; color: root.page === index ? root.accent : root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.icon }
                    Column {
                      anchors.verticalCenter: parent.verticalCenter
                      Text { text: modelData.title; color: root.page === index ? root.accent : root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.body }
                      Text { text: modelData.subtitle; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
                    }
                  }
                  MouseArea {
                    id: navMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                      root.page = index
                      root.message = "Ready"
                      if (index === 2) root.run("snapshot-preview", ["--json", "snapshot"])
                      else if (index === 3) root.run("restore-preview", ["--json", "restore"])
                      else if (index === 4) root.run("seed", ["--json", "seed", "--stage", "check"])
                    }
                  }
                }
              }

              Item { width: 1; height: Style.space(8) }
              Rectangle { width: parent.width; height: 1; color: Util.alpha(root.border, 0.6) }
              Text { width: parent.width; text: root.repository; textFormat: Text.PlainText; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideMiddle }
              Text { text: root.repoState === "clean" ? "● Clean" : (root.repoState === "dirty" ? "● Changes pending" : "● Setup required"); color: root.repoState === "clean" ? root.accent : root.urgent; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
            }
          }

          Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: root.border }

          Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
              anchors.fill: parent
              anchors.margins: Style.space(24)
              spacing: Style.space(16)

              RowLayout {
                Layout.fillWidth: true
                Column {
                  Layout.fillWidth: true
                  Text { text: root.pages[root.page].title; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.heading }
                  Text { text: root.pages[root.page].subtitle; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall }
                }
                Button { text: "󰑐  Refresh"; bordered: true; enabled: !process.running; onClicked: root.refresh() }
                Button { text: "󰑐  Fetch remote"; bordered: true; enabled: !process.running && root.origin !== ""; onClicked: root.fetchRemoteStatus() }
                Button { text: "Close"; bordered: true; onClicked: root.dismiss() }
              }

              Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: root.border }

              Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                Column {
                  visible: root.page === 0
                  anchors.fill: parent
                  spacing: Style.space(16)

                  Row {
                    width: parent.width
                    spacing: Style.space(10)
                    Repeater {
                      model: [
                        { label: "Snapshot pending", value: String(root.snapshotPending), icon: "󰆓" },
                        { label: "Repository changes", value: String(root.dirty), icon: "󰜄" },
                        { label: "Unpushed commits", value: String(root.ahead), icon: "󰜘" },
                        { label: "Remote updates", value: String(root.behind), icon: "󰇚" }
                      ]
                      BorderSurface {
                        required property var modelData
                        width: (parent.width - Style.space(30)) / 4
                        height: Style.space(100)
                        color: Util.alpha(root.foreground, 0.035)
                        borderSpec: Border.flat(Util.alpha(root.border, 0.7), 1)
                        radius: Style.cornerRadius
                        padding: Style.space(12)
                        Column {
                          anchors.fill: parent
                          anchors.margins: Style.space(14)
                          spacing: Style.space(8)
                          Text { text: modelData.icon; color: root.accent; font.family: root.fontFamily; font.pixelSize: Style.font.icon }
                          Text { text: modelData.value; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.title; elide: Text.ElideRight; width: parent.width }
                          Text { text: modelData.label; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
                        }
                      }
                    }
                  }

                  BorderSurface {
                    width: parent.width
                    height: Style.space(116)
                    color: Util.alpha(root.foreground, 0.025)
                    borderSpec: Border.flat(Util.alpha(root.border, 0.65), 1)
                    radius: Style.cornerRadius
                    padding: Style.space(16)
                    Column {
                      anchors.fill: parent
                      anchors.margins: Style.space(16)
                      spacing: Style.space(8)
                      Text { text: "Configuration repository"; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
                      Text { width: parent.width; text: root.repository; textFormat: Text.PlainText; color: root.foreground; font.family: "monospace"; font.pixelSize: Style.font.body; elide: Text.ElideMiddle }
                      Text { width: parent.width; text: root.origin || "No origin configured"; textFormat: Text.PlainText; color: root.muted; font.family: "monospace"; font.pixelSize: Style.font.bodySmall; elide: Text.ElideMiddle }
                    }
                  }

                  Row { spacing: Style.space(10)
                    Button { text: "Preview snapshot"; bordered: true; onClicked: { root.page = 2; root.run("snapshot-preview", ["--json", "snapshot"]) } }
                    Button { text: "Preview restore"; bordered: true; onClicked: { root.page = 3; root.run("restore-preview", ["--json", "restore"]) } }
                    Button { text: "Open repository"; bordered: true; enabled: root.repoState !== "uninitialized"; onClicked: root.run("repo-open", ["repo", "open"]) }
                  }
                }

                Column {
                  visible: root.page === 1
                  anchors.fill: parent
                  spacing: Style.space(16)

                  Text { text: "Configuration repository"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.title }
                  Text { width: parent.width; text: "This machine-local selection is stored under ~/.config/omarchy and is never captured into plugin source."; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap }
                  RowLayout { width: parent.width; spacing: Style.space(8)
                    TextField { Layout.fillWidth: true; text: root.repoDraft; placeholderText: "~/Work/omarchy-config"; onTextChanged: root.repoDraft = text }
                    Button { text: "Select"; bordered: true; enabled: root.repoDraft.trim() !== "" && !process.running; onClicked: root.run("config-select", ["--json", "config", "select", root.repoDraft.trim()]) }
                    Button { text: "Initialize"; bordered: true; enabled: !process.running; onClicked: root.run("repo-init", ["--json", "repo", "init"]) }
                  }

                  Rectangle { width: parent.width; height: 1; color: root.border }
                  Text { text: "Git origin"; color: root.foreground; font.family: root.fontFamily; font.pixelSize: Style.font.title }
                  Text { width: parent.width; text: "SSH and HTTPS are supported. Authentication stays with Git and SSH; credential-bearing URLs are rejected."; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap }
                  TextField { width: parent.width; text: root.originDraft; placeholderText: "git@github.com:you/omarchy-config.git"; onTextChanged: root.originDraft = text }
                  Row { spacing: Style.space(8)
                    Button { text: root.origin === "" ? "Set origin" : "Replace origin"; bordered: true; enabled: root.originDraft.trim() !== "" && !process.running; onClicked: root.run("origin-set", ["--json", "repo", "origin", "set", root.originDraft.trim()]) }
                    Button { text: "Test access"; bordered: true; enabled: root.originDraft.trim() !== "" && !process.running; onClicked: root.run("origin-test", ["--json", "repo", "origin", "test", root.originDraft.trim()]) }
                    Button { text: "Show origin"; bordered: true; enabled: !process.running; onClicked: root.run("origin-show", ["--json", "repo", "origin", "show"]) }
                    Button { text: "Remove origin"; bordered: true; foreground: root.urgent; accent: root.urgent; enabled: root.origin !== "" && !process.running; onClicked: root.requestConfirmation("origin") }
                  }
                }

                Column {
                  visible: root.page === 2
                  anchors.fill: parent
                  spacing: Style.space(12)
                  Text { width: parent.width; text: "Preview the allowlisted capture first. Applying updates only the configuration repository—it never stages, commits, or pushes."; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap }
                  Row { spacing: Style.space(8)
                    Button { text: "Preview snapshot"; bordered: true; enabled: !process.running; onClicked: root.run("snapshot-preview", ["--json", "snapshot"]) }
                    Button { text: "Apply reviewed snapshot"; bordered: true; foreground: root.accent; accent: root.accent; enabled: !process.running; onClicked: root.requestConfirmation("snapshot") }
                    Button { text: "Open repository"; bordered: true; onClicked: root.run("repo-open", ["repo", "open"]) }
                  }
                  Rectangle { width: parent.width; height: 1; color: root.border }
                  RowLayout {
                    width: parent.width
                    spacing: Style.space(8)
                    TextField { Layout.fillWidth: true; text: root.commitMessage; placeholderText: "Commit message"; onTextChanged: root.commitMessage = text }
                    Button { text: "Commit snapshot"; bordered: true; enabled: root.commitMessage.trim() !== "" && root.dirty > 0 && !process.running; onClicked: root.requestConfirmation("commit") }
                    Button { text: "Push commits"; bordered: true; enabled: root.origin !== "" && !process.running; onClicked: root.requestConfirmation("push") }
                  }
                  OutputPanel { width: parent.width; height: parent.height - Style.space(165); title: "Snapshot and Git review"; content: root.detail; foreground: root.foreground; muted: root.muted; borderColor: root.border; fontFamily: root.fontFamily }
                }

                Column {
                  visible: root.page === 3
                  anchors.fill: parent
                  spacing: Style.space(12)
                  Text { width: parent.width; text: "Restore is always dry-run first. Portable files are the default; device-specific monitor and input settings remain separated."; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap }
                  Row { spacing: Style.space(8)
                    Button { text: root.includeDevice ? "Device files included" : "Portable files only"; bordered: true; onClicked: root.includeDevice = !root.includeDevice }
                    Button { text: "Preview restore"; bordered: true; enabled: !process.running; onClicked: { var args=["--json","restore"]; if(root.includeDevice)args.push("--include-device"); root.run("restore-preview",args) } }
                    Button { text: "Apply reviewed restore"; bordered: true; foreground: root.urgent; accent: root.urgent; enabled: !process.running; onClicked: root.requestConfirmation("restore") }
                  }
                  OutputPanel { width: parent.width; height: parent.height - Style.space(105); title: "Restore preview"; content: root.detail; foreground: root.foreground; muted: root.muted; borderColor: root.border; fontFamily: root.fontFamily }
                }

                Column {
                  visible: root.page === 4
                  anchors.fill: parent
                  spacing: Style.space(12)
                  Text { width: parent.width; text: "A staged, approval-first plan for preparing another Omarchy laptop. Package and plugin installation remain separate approval boundaries."; color: root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap }
                  Row { spacing: Style.space(6)
                    Button { text: "󰋖  Help"; bordered: true; onClicked: root.showSeedHelp() }
                    Repeater {
                      model: ["check", "restore", "packages", "plugins", "mime", "reload", "report"]
                      Button { required property string modelData; text: modelData; bordered: true; enabled: !process.running; onClicked: root.run("seed", ["--json", "seed", "--stage", modelData]) }
                    }
                  }
                  OutputPanel { width: parent.width; height: parent.height - Style.space(105); title: "Seed plan"; content: root.detail; foreground: root.foreground; muted: root.muted; borderColor: root.border; fontFamily: root.fontFamily }
                }
              }

              BorderSurface {
                Layout.fillWidth: true
                Layout.preferredHeight: Style.space(38)
                color: root.actionFailed ? Util.alpha(root.urgent, 0.1) : Util.alpha(root.foreground, 0.025)
                borderSpec: Border.flat(root.actionFailed ? Util.alpha(root.urgent, 0.55) : Util.alpha(root.border, 0.6), 1)
                radius: Style.cornerRadius
                padding: Style.space(9)
                Row {
                  anchors.fill: parent
                  anchors.margins: Style.space(9)
                  spacing: Style.space(8)
                  Text { text: process.running ? "󰑓" : (root.actionFailed ? "󰅙" : "󰄬"); color: root.actionFailed ? root.urgent : root.accent; font.family: root.fontFamily; font.pixelSize: Style.font.body }
                  Text { width: parent.width - Style.space(32); text: root.message; textFormat: Text.PlainText; color: root.actionFailed ? root.urgent : root.muted; font.family: root.fontFamily; font.pixelSize: Style.font.caption; elide: Text.ElideRight }
                }
              }
            }

            ConfirmDialog {
              id: confirmDialog
              anchors.fill: parent
              background: root.background
              foreground: root.foreground
              selectedText: root.accent
              fontFamily: root.fontFamily
              onCanceled: opened = false
              onConfirmed: root.runConfirmed()
            }

            Item {
              anchors.fill: parent
              visible: root.easterEggOpen
              z: 20

              Rectangle {
                anchors.fill: parent
                color: Util.alpha(root.background, 0.76)
                MouseArea { anchors.fill: parent; onClicked: root.easterEggOpen = false }
              }

              BorderSurface {
                width: Math.min(parent.width - Style.space(48), Style.space(480))
                height: Style.space(225)
                anchors.centerIn: parent
                color: root.background
                borderSpec: Border.flat(root.accent, Style.normalBorderWidth)
                radius: Style.cornerRadius
                padding: Style.space(22)

                MouseArea { anchors.fill: parent; onClicked: {} }

                Column {
                  anchors.fill: parent
                  anchors.margins: Style.space(22)
                  spacing: Style.space(14)

                  Text {
                    text: "For Synchro"
                    color: root.accent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.heading
                  }

                  Text {
                    width: parent.width
                    text: "This plugin is dedicated to the memory of my friend Synchro, aka Jeroen Van Garling."
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.title
                    wrapMode: Text.WordWrap
                  }

                  Item { width: 1; height: Style.space(4) }

                  Row {
                    spacing: Style.space(10)
                    Button { text: "Close"; bordered: true; onClicked: root.easterEggOpen = false }
                    Button {
                      text: "󰎆  Listen to Synchro"
                      bordered: true
                      foreground: root.accent
                      accent: root.accent
                      onClicked: {
                        root.easterEggOpen = false
                        Quickshell.execDetached(["xdg-open", "https://open.spotify.com/artist/1MY1c4WZ6MFefT5EqarUmw?si=eFD2XZ8xTr-WppsVryvgXg"])
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  Process {
    id: process
    property string capturedStdout: ""
    property string capturedStderr: ""
    property int outputBytes: 0
    property bool outputTruncated: false
    readonly property int outputLimit: 65536
    function capture(line, isError) {
      if (outputTruncated) return
      var chunk = String(line || "")
      var remaining = outputLimit - outputBytes
      if (chunk.length > remaining) {
        chunk = chunk.substring(0, Math.max(0, remaining))
        outputTruncated = true
      }
      outputBytes += chunk.length
      if (isError) capturedStderr += chunk
      else capturedStdout += chunk
    }
    stdout: SplitParser { onRead: function(line) { process.capture(line, false) } }
    stderr: SplitParser { onRead: function(line) { process.capture(line, true) } }
    onExited: function(exitCode) {
      var raw = process.outputTruncated
        ? '{"error":"Plugin output exceeded the safe UI limit. Run the CLI for full details."}'
        : (process.capturedStderr.trim() !== "" ? process.capturedStderr.trim() : process.capturedStdout.trim())
      var data = root.parse(raw)
      root.actionFailed = exitCode !== 0 || (data !== null && data.error !== undefined)
      var rendered = root.friendlyOutput(data, raw)
      if (["status", "status-fetch", "overview"].indexOf(root.action) < 0 || root.actionFailed) root.detail = rendered
      root.message = root.actionFailed ? rendered.split("\n")[0] : "Action completed successfully."

      if ((root.action === "status" || root.action === "status-fetch") && !root.actionFailed) {
        root.applyStatus(data)
        root.message = root.action === "status-fetch" ? "Remote status fetched." : "Repository status refreshed."
      } else if (root.action === "overview" && !root.actionFailed) {
        root.applyOverview(data)
        root.message = root.snapshotPending > 0
          ? root.snapshotPending + " snapshot change" + (root.snapshotPending === 1 ? "" : "s") + " pending."
          : "Snapshot and repository status refreshed."
      } else if (root.action === "config-select") {
        root.repository = data && data.selected ? String(data.selected) : root.repoDraft
        root.repoDraft = root.repository
        root.message = "Configuration repository selected. Initialize it when ready."
      } else if (root.action === "origin-show") {
        root.origin = data && data.origin ? String(data.origin) : ""
        root.originDraft = root.origin
        root.message = root.origin === "" ? "No origin is configured." : "Origin loaded."
      } else if (root.action === "seed" && !root.actionFailed) {
        root.message = data && data.summary ? String(data.summary) : "Seed stage preview loaded."
      } else if (!root.actionFailed && ["repo-init", "origin-set", "origin-remove", "snapshot-apply", "repo-commit", "repo-push"].indexOf(root.action) >= 0) {
        Qt.callLater(root.refresh)
      }
    }
  }

  component OutputPanel: BorderSurface {
    id: outputPanel
    property string title: "Output"
    property string content: "Run a preview to see changes here."
    property color foreground: Color.foreground
    property color muted: Qt.darker(foreground, 1.5)
    property color borderColor: Color.accent
    property string fontFamily: Style.font.family
    color: Util.alpha(foreground, 0.025)
    borderSpec: Border.flat(Util.alpha(borderColor, 0.7), 1)
    radius: Style.cornerRadius
    padding: Style.space(14)
    Column {
      anchors.fill: parent
      anchors.margins: Style.space(14)
      spacing: Style.space(10)
      Text { text: outputPanel.title.toUpperCase(); textFormat: Text.PlainText; color: outputPanel.muted; font.family: outputPanel.fontFamily; font.pixelSize: Style.font.caption }
      Flickable {
        width: parent.width; height: parent.height - Style.space(30)
        contentWidth: width; contentHeight: outputText.implicitHeight
        clip: true; boundsBehavior: Flickable.StopAtBounds
        Text { id: outputText; width: parent.width; text: outputPanel.content || "Run a preview to see changes here."; textFormat: Text.PlainText; color: outputPanel.foreground; font.family: "monospace"; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WrapAnywhere }
      }
    }
  }
}
