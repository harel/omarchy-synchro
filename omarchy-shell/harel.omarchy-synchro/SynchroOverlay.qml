import QtQuick
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
  property string output: "Loading…"
  property string cli: localPath(Qt.resolvedUrl("cli.sh"))
  function localPath(url) { var value=String(url); if(value.indexOf("file://")===0)value=value.substring(7); return decodeURIComponent(value) }
  function open(payloadJson) { opened=true; run(["--json","status"]) }
  function close() { opened=false }
  function dismiss() { opened=false; if(shell) shell.hide("harel.omarchy-synchro") }
  function run(args) { if(proc.running)return; output="Working…"; proc.command=[cli].concat(args); proc.running=true }
  PanelWindow {
    id: panel; visible: root.opened
    anchors { top:true; bottom:true; left:true; right:true }
    color: "transparent"; WlrLayershell.namespace: "harel-omarchy-synchro"; WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive; exclusionMode: ExclusionMode.Ignore
    Rectangle { anchors.fill: parent; color: Color.menu.scrim }
    MouseArea { anchors.fill: parent; onClicked: root.dismiss() }
    BorderSurface {
      width: Math.min(Style.space(650), panel.width-Style.gapsOut*2); height: Math.min(Style.space(520), panel.height-Style.gapsOut*2)
      anchors.centerIn: parent; color: Color.menu.background; radius: Style.cornerRadius
      borderSpec: Border.surfaceSpec("menu","border",Color.menu.border,Math.max(1,Style.space(2))); padding: Style.spacing.panelPadding
      MouseArea { anchors.fill: parent; onClicked: {} }
      Column {
        anchors.fill: parent; spacing: Style.space(12)
        Text { text:"Omarchy Synchro"; color:Color.menu.text; font.family:Style.font.menuFamily; font.pixelSize:Style.font.title }
        Text { width:parent.width; height:Style.space(310); text:root.output; color:Color.menu.text; font.family:"monospace"; font.pixelSize:Style.font.bodySmall; wrapMode:Text.WrapAnywhere; elide:Text.ElideRight }
        Row { spacing:Style.space(8)
          Button { text:"Status"; bordered:true; onClicked:root.run(["--json","status"]) }
          Button { text:"Preview snapshot"; bordered:true; onClicked:root.run(["--json","snapshot"]) }
          Button { text:"Apply snapshot"; bordered:true; onClicked:root.run(["--json","snapshot","--apply"]) }
          Button { text:"Preview restore"; bordered:true; onClicked:root.run(["--json","restore"]) }
          Button { text:"Open repo"; bordered:true; onClicked:root.run(["repo","open"]) }
          Button { text:"Close"; bordered:true; onClicked:root.dismiss() }
        }
      }
    }
  }
  Process {
    id:proc; property string captured:""
    stdout: StdioCollector { waitForEnd:true; onStreamFinished:proc.captured=text.trim() }
    stderr: StdioCollector { waitForEnd:true; onStreamFinished:if(text.trim())proc.captured=text.trim() }
    onExited:function(code){ root.output=(code===0?"":"ERROR\n")+(captured||"No output") }
  }
}

