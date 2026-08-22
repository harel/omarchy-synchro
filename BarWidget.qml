import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "harel.omarchy-synchro"
  property string state: "loading"
  property int dirty: 0
  property string cli: localPath(Qt.resolvedUrl("cli.sh"))
  function localPath(url) { var value=String(url); if (value.indexOf("file://")===0) value=value.substring(7); return decodeURIComponent(value) }
  function refresh() { status.command=[cli,"--qml","--json","status"]; if (!status.running) status.running=true }
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.state === "clean" ? "󰘬" : (root.state === "loading" ? "󰑓" : "󰓦")
    tooltipText: root.state === "uninitialized" ? "Omarchy Synchro · initialize repository" : "Omarchy Synchro · " + root.dirty + " changed files"
    horizontalMargin: 10
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton && root.bar && root.bar.shell) root.bar.shell.summon("harel.omarchy-synchro", "{}")
    }
  }
  Process {
    id: status
    stdout: SplitParser {
      onRead: function(line) {
        if (line.length > 65536) { root.state="error"; return }
        try { var d=JSON.parse(line); root.state=d.state||"error"; root.dirty=(d.dirtyFiles||[]).length }
        catch(e) { root.state="error" }
      }
    }
    stderr: SplitParser { onRead: function(line) { root.state="error" } }
  }
  Timer { interval: 30000; repeat: true; running: true; triggeredOnStart: true; onTriggered: root.refresh() }
}
