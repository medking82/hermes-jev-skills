import AppKit
import Foundation

// Owned, synthetic desktop surface. No network, real records, account or outbound action.
let folder = URL(fileURLWithPath: CommandLine.arguments[1])
func save(_ state: [String:Any]) { if let data = try? JSONSerialization.data(withJSONObject:state,options:[.sortedKeys]) { try? data.write(to:folder.appendingPathComponent("state.json"),options:.atomic) } }
final class Backdrop:NSView {
 override func draw(_ rect:NSRect) {
  NSColor(calibratedRed:0.035,green:0.05,blue:0.10,alpha:1).setFill(); bounds.fill()
  NSColor(calibratedRed:0.08,green:0.13,blue:0.22,alpha:1).setFill(); NSBezierPath(roundedRect:NSRect(x:32,y:28,width:1216,height:548),xRadius:28,yRadius:28).fill()
 }
}
final class Demo:NSObject,NSApplicationDelegate,NSTextFieldDelegate {
 var window:NSWindow!; var note:NSTextField!; var status:NSTextField!; var telemetry:NSTextField!; var mission:NSTextField!
 var selected="None"; var preview=false; var visual="None"; var timer:Timer!; var last=""
 func text(_ s:String,_ x:CGFloat,_ y:CGFloat,_ w:CGFloat,_ size:CGFloat,_ color:NSColor = .white)->NSTextField {
  let v=NSTextField(labelWithString:s); v.frame=NSRect(x:x,y:y,width:w,height:size*1.7);v.font=NSFont.systemFont(ofSize:size,weight:.semibold);v.textColor=color;window.contentView!.addSubview(v);return v
 }
 func button(_ s:String,_ x:CGFloat,_ y:CGFloat,_ w:CGFloat,_ action:Selector,_ tag:Int=0)->NSButton {
  let b=NSButton(title:s,target:self,action:action);b.frame=NSRect(x:x,y:y,width:w,height:58);b.bezelStyle = .rounded;b.font=NSFont.systemFont(ofSize:22,weight:.semibold);b.tag=tag;window.contentView!.addSubview(b);return b
 }
 func applicationDidFinishLaunching(_ n:Notification) {
  window=NSWindow(contentRect:NSRect(x:190,y:180,width:1280,height:720),styleMask:[.titled,.closable],backing:.buffered,defer:false)
  window.title="Jev Image Demo Lab";window.contentView=Backdrop(frame:NSRect(x:0,y:0,width:1280,height:720));window.isReleasedWhenClosed=false
  _=text("JEV + HERMES",48,642,800,40);_=text("Real decisions. Real clicks. Synthetic workspace.",50,601,1100,22,.lightGray)
  _=text("01  CHOOSE A WORKSPACE",64,507,700,20,.cyan)
  _=button("Orbit",64,431,240,#selector(workspace(_:)),1);_=button("Garden",324,431,240,#selector(workspace(_:)),2);_=button("Rocket",584,431,240,#selector(workspace(_:)),3)
  mission=text("Selected: None",64,386,1100,22)
  _=text("02  TYPE A MISSION NOTE",64,327,700,20,.cyan)
  note=NSTextField(frame:NSRect(x:64,y:261,width:760,height:52));note.placeholderString="Mission note";note.setAccessibilityLabel("Mission note");note.font=NSFont.systemFont(ofSize:25);note.delegate=self;window.contentView!.addSubview(note)
  _=button("Preview",853,261,280,#selector(showPreview(_:)))
  status=text("Waiting for Jev",64,201,1100,27,.white)
  _=text("VISUAL CHECK",64,126,350,18,.lightGray)
  for (i,color) in [NSColor.systemPurple,NSColor.systemTeal,NSColor.systemOrange].enumerated() { let b=button(["A","B","C"][i],CGFloat(64+i*130),61,110,#selector(tile(_:)),i);b.contentTintColor=color;b.bezelColor=color }
  telemetry=text("Decision timing appears after each live call",498,70,700,19,.cyan)
  _=text("Experimental image input  |  Only prevalidated action IDs execute",48,9,1200,16,.lightGray)
  window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true);record()
  timer=Timer.scheduledTimer(withTimeInterval:0.08,repeats:true){_ in
   guard let d=try? Data(contentsOf:folder.appendingPathComponent("control.json")),let c=try? JSONSerialization.jsonObject(with:d) as? [String:String],let line=c["line"],line != self.last else{return};self.last=line;self.telemetry.stringValue=line
   if c["reset"]=="fresh-fixture" { self.selected="None";self.preview=false;self.visual="None";self.note.stringValue="";self.mission.stringValue="Selected: None";self.status.stringValue="Fresh local fixture";self.record() }
  }
 }
 func record(){save(["selected":selected,"note":note.stringValue,"preview":preview,"visual":visual])}
 func controlTextDidChange(_ n:Notification){record()}
 @objc func workspace(_ b:NSButton){selected=b.title;preview=false;mission.stringValue="Selected: \(selected)";status.stringValue="Workspace ready";record()}
 @objc func showPreview(_ b:NSButton){preview=selected=="Rocket" && note.stringValue=="LAUNCH READY";status.stringValue=preview ? "LAUNCH READY  -  Verified!" : "Choose Rocket and type LAUNCH READY";record()}
 @objc func tile(_ b:NSButton){visual=["A","B","C"][b.tag];status.stringValue="Visual tile \(visual) selected";record()}
}
let app=NSApplication.shared;app.setActivationPolicy(.regular);let demo=Demo();app.delegate=demo;app.run()
