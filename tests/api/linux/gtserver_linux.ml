
module Protocol = Gtcomms.Make_Protocol (struct type t=Gtmessages.message end)
module Client = Gtcomms.Client (Protocol)
module Server = Gtcomms.Server (Protocol)

module GuestOp=Gtlinuxops

open Gtmessages

class server n np =
  object (self)
    inherit [message] Server.server n np

    method shutdown s timeout =
      self#send s (CmdResult "Shutdown called!");
      ignore(GuestOp.shutdown timeout)

    method reboot s timeout =
      self#send s (CmdResult "Reboot called!");
      ignore(GuestOp.reboot timeout)

    method crash s =
      GuestOp.crash ();
      self#send s (CmdResult "You might not get this...")
	
    method test s =
      self#send s (CmdResult "Test worked OK!")

    method checkcds s devices =
      self#send s (GuestOp.checkcds devices)
	
    method checkvif s device =
      self#send s (GuestOp.checkvifs device)  
	
    method checkdisks s devices =
      self#send s (GuestOp.checkdisks devices)

    method checkmountdisks s devices =
      self#send s (GuestOp.checkmountdisks devices)

    method setuptestdisk s device =
      self#send s (GuestOp.setuptestdisk device)

    method process s = 
      begin
	match self#receive s with
          Shutdown timeout -> self#shutdown s timeout
	| Reboot timeout -> self#reboot s timeout
	| Test -> self#test s 
	| Crash -> self#crash s
	| CheckCD devs -> self#checkcds s devs
	| CheckVIF dev -> self#checkvif s dev
	| CheckDisks devs -> self#checkdisks s devs
	| CheckMountDisks devs -> self#checkmountdisks s devs
	| SetupTestDisk dev -> self#setuptestdisk s dev
	| _ -> ()
      end;
      Unix.close s
	
  end

let _ =
  let port = 8085 in
  let s = new server port 1 in
  s#start

