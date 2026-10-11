using System;
using System.IO;
using System.Text;
using System.Security.Cryptography;
using System.Collections.Generic;

static class ConnectionChecks {
    static int Main() {
        string trial=Path.Combine(Path.GetTempPath(),"qr-inbox-connection-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(trial);
        InboxApp.Home=trial;
        try {
            string expected="https://another-shop.example.com/desktop";
            if(InboxApp.ValidateRelay(expected+"/")!=expected) throw new Exception("Custom relay rejected");
            foreach(string bad in new [] {"http://shop.example.com/desktop", "https://user:pass@shop.example.com/desktop",
                "https://shop.example.com/desktop?key=abc", "https://shop.example.com/desktop#fragment",
                "https://shop.example.com:8443/desktop", "https://127.0.0.1/desktop", "https://localhost/desktop",
                "https://shop.example.com/wrong"}) {
                bool rejected=false;
                try { InboxApp.ValidateRelay(bad); } catch(IOException) { rejected=true; }
                if(!rejected) throw new Exception("Unsafe relay accepted");
            }
            string key=new string('a',48);
            string source=Path.Combine(trial,"test.connection.json");
            File.WriteAllText(source,InboxApp.Json.Serialize(new {gateway_secret=key,relay_url=expected}));
            InboxApp.Import(source);
            byte[] cipher=File.ReadAllBytes(InboxApp.Config);
            if(Encoding.UTF8.GetString(cipher).Contains(key)) throw new Exception("Plaintext saved");
            string plain=Encoding.UTF8.GetString(ProtectedData.Unprotect(cipher,null,DataProtectionScope.CurrentUser));
            var saved=InboxApp.Json.Deserialize<Dictionary<string,object>>(plain);
            if(Convert.ToString(saved["relay_url"])!=expected || Convert.ToString(saved["gateway_secret"])!=key)
                throw new Exception("Connection roundtrip failed");
            File.WriteAllText(source,InboxApp.Json.Serialize(new {gateway_secret="short",relay_url=expected}));
            bool invalid=false;
            try { InboxApp.Import(source); } catch(IOException) { invalid=true; }
            if(!invalid || Convert.ToBase64String(File.ReadAllBytes(InboxApp.Config))!=Convert.ToBase64String(cipher))
                throw new Exception("Invalid import replaced valid connection");
            Console.WriteLine("PASS: custom HTTPS relay, unsafe URL rejection, DPAPI key/address roundtrip, invalid import preserves settings");
            return 0;
        } finally { Directory.Delete(trial,true); }
    }
}
