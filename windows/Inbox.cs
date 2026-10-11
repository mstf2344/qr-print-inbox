using System;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Text;
using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Drawing;
using System.Web.Script.Serialization;
using Microsoft.Win32;
using System.Collections.Generic;

static class InboxApp {
    internal static string Home = Environment.GetEnvironmentVariable("QR_INBOX_TEST_HOME") ??
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "QRPrintInbox", "desktop");
    internal static string Install = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Programs", "QRPrintInbox");
    internal static string Relay;
    internal static JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 24000 };
    internal static string Exe { get { return Assembly.GetExecutingAssembly().Location; } }
    internal static string Config { get { return Path.Combine(Home,"connection.bin"); } }
    internal static string Stop { get { return Path.Combine(Home,"stop.request"); } }
    internal static string State { get { return Path.Combine(Home,"status.txt"); } }
    internal static string Device { get { return Path.Combine(Home,"device.txt"); } }
    internal static string Key;
    internal static string Id;
    internal static int Port = 8031;

    [STAThread] static int Main(string[] args) {
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
        ServicePointManager.DefaultConnectionLimit = 16;
        ServicePointManager.Expect100Continue = false;
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        Directory.CreateDirectory(Home);
        try {
            if (args.Length>0 && args[0]=="/self-test") {
                File.WriteAllText(Path.Combine(Home,"self-test.txt"),
                    "x86="+(!Environment.Is64BitProcess)+"; framework="+Environment.Version);
                return Environment.Is64BitProcess ? 1 : 0;
            }
            if (!FrameworkReady()) {
                MessageBox.Show("Bu uygulama .NET Framework 4.8 gerektirir. Windows 7 için SP1 de gereklidir.\nMicrosoft kurulum sayfası açılacak.","QR File Inbox");
                Process.Start("https://support.microsoft.com/help/4503548"); return 1;
            }
            if (args.Length>1 && args[0]=="/import") { Import(args[1]); return 0; }
            if (args.Length>0 && args[0]=="/stop") { File.WriteAllText(Stop,""); return 0; }
            if (args.Length>0 && args[0]=="/start") { Start(); return 0; }
            if (args.Length>0 && args[0]=="/background") { Run(); return 0; }
            if (args.Length>1 && args[0]=="/extract") { Extract(args[1]); return 0; }
            if (args.Length>0 && args[0]=="/install") { InstallNow(false); return 0; }
            Application.Run(new PanelForm(Path.GetFileNameWithoutExtension(Exe).Contains("Kurulum")));
            return 0;
        } catch(Exception error) {
            File.WriteAllText(Path.Combine(Home,"operation-error.txt"),error.GetType().Name+"\n"+error.StackTrace);
            if (args.Length==0) MessageBox.Show("İşlem tamamlanamadı. Disk alanını, dosya izinlerini ve bağlantı ayarını kontrol edin.","QR File Inbox");
            return 1;
        }
    }
    static bool FrameworkReady() {
        using (RegistryKey k=RegistryKey.OpenBaseKey(RegistryHive.LocalMachine,RegistryView.Registry32)
            .OpenSubKey(@"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full")) {
            return k!=null && Convert.ToInt32(k.GetValue("Release",0))>=528040;
        }
    }
    internal static void Import(string path) {
        if (new FileInfo(path).Length>4096) throw new IOException();
        var obj=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path,Encoding.UTF8));
        string secret=Convert.ToString(obj["gateway_secret"]);
        if (!System.Text.RegularExpressions.Regex.IsMatch(secret,@"\A[A-Za-z0-9_-]{32,128}\z")) throw new IOException();
        string relay=ValidateRelay(Convert.ToString(obj["relay_url"]));
        if (IsRunning()) throw new IOException("Önce servisi durdurun.");
        string saved=Json.Serialize(new {gateway_secret=secret,relay_url=relay});
        byte[] protectedBytes=ProtectedData.Protect(Encoding.UTF8.GetBytes(saved),null,DataProtectionScope.CurrentUser);
        string temp=Config+".new"; File.WriteAllBytes(temp,protectedBytes);
        if (File.Exists(Config)) File.Replace(temp,Config,null); else File.Move(temp,Config);
    }
    internal static string ValidateRelay(string value) {
        Uri url;
        if(!Uri.TryCreate(value,UriKind.Absolute,out url) || url.Scheme!="https" ||
            !url.IsDefaultPort || url.UserInfo!="" || url.Query!="" || url.Fragment!="" ||
            url.HostNameType!=UriHostNameType.Dns || url.IsLoopback ||
            !(url.AbsolutePath=="/desktop" || url.AbsolutePath=="/desktop/")) throw new IOException();
        return url.GetLeftPart(UriPartial.Authority)+"/desktop";
    }
    static void LoadConnection() {
        string saved=Encoding.UTF8.GetString(ProtectedData.Unprotect(File.ReadAllBytes(Config),null,DataProtectionScope.CurrentUser));
        // Older versions saved only a key. Re-import the original connection JSON once.
        if(!saved.StartsWith("{")) throw new IOException("Bağlantı dosyasını yeniden seçin.");
        var obj=Json.Deserialize<Dictionary<string,object>>(saved);
        Key=Convert.ToString(obj["gateway_secret"]);
        Relay=ValidateRelay(Convert.ToString(obj["relay_url"]));
    }
    static bool IsRunning() {
        try { using(var f=new FileStream(Path.Combine(Home,"service.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)) return false; }
        catch(IOException) { return true; }
    }
    internal static void Start() {
        if (!File.Exists(Config)) throw new IOException("Önce bağlantı dosyasını seçin.");
        if (IsRunning()) return;
        File.Delete(Stop);
        Process.Start(new ProcessStartInfo(Exe,"/background") {UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=Path.GetDirectoryName(Exe)});
    }
    static HttpWebRequest Request(string url,string method,bool agent) {
        var req=(HttpWebRequest)WebRequest.Create(url);
        req.Method=method; req.Timeout=200000; req.ReadWriteTimeout=190000;
        req.AllowAutoRedirect=false; req.Proxy=null; req.KeepAlive=true;
        if(agent) { req.Headers["X-Inbox-Agent"]=Key; req.Headers["X-Inbox-Device"]=Id; }
        return req;
    }
    static HttpWebResponse Response(HttpWebRequest req) {
        try { return (HttpWebResponse)req.GetResponse(); }
        catch(WebException e) { if(e.Response!=null) return (HttpWebResponse)e.Response; throw; }
    }
    static string ReadSmall(Stream stream) {
        using(var memory=new MemoryStream()) {
            byte[] buffer=new byte[4096]; int n;
            while((n=stream.Read(buffer,0,buffer.Length))>0) { if(memory.Length+n>20000) throw new IOException(); memory.Write(buffer,0,n); }
            return Encoding.UTF8.GetString(memory.ToArray());
        }
    }
    static string Agent(string path,string content) {
        var req=Request(Relay+path,content==null ? "GET":"POST",true);
        req.Timeout=path=="/bridge/poll" ? 30000 : 5000;
        req.ReadWriteTimeout=req.Timeout;
        if(content!=null) { byte[] bytes=Encoding.UTF8.GetBytes(content); req.ContentType="application/json";
            req.ContentLength=bytes.Length; using(var s=req.GetRequestStream()) s.Write(bytes,0,bytes.Length); }
        using(var response=Response(req)) {
            if((int)response.StatusCode!=200) throw new IOException();
            return ReadSmall(response.GetResponseStream());
        }
    }
    static void Job(Dictionary<string,object> job) {
        string id=Convert.ToString(job["id"]),path=Convert.ToString(job["path"]);
        // The relay cannot turn this client into a proxy to arbitrary hosts or local routes.
        if(!System.Text.RegularExpressions.Regex.IsMatch(path,
            @"\A(/healthz|/api/v1/config|/api/v1/sessions|/api/v1/sessions/[A-Za-z0-9_-]{43}/(files|status|finalize))\z")) throw new IOException();
        string method=Convert.ToString(job["method"]);
        if(method!="GET" && method!="POST") throw new IOException();
        var local=Request("http://127.0.0.1:"+Port+path,method,false);
        local.Headers["X-Inbox-Gateway"]=Key;
        local.Headers["X-Inbox-Client-IP"]=Convert.ToString(job["ip"]);
        if(path.EndsWith("/files")) {
            local.ContentType="application/octet-stream";
            local.Headers["X-File-Name"]=Convert.ToString(job["filename"]);
            local.AllowWriteStreamBuffering=false; local.SendChunked=true;
            var body=Request(Relay+"/bridge/body/"+id,"GET",true);
            using(var response=Response(body)) {
                if((int)response.StatusCode!=200) throw new IOException();
                using(var source=response.GetResponseStream()) using(var target=local.GetRequestStream()) {
                    byte[] buffer=new byte[65536]; int n; long total=0;
                    while((n=source.Read(buffer,0,buffer.Length))>0) {
                        if(File.Exists(Stop)) throw new IOException();
                        total+=n; if(total>25L*1024*1024) throw new IOException(); target.Write(buffer,0,n);
                    }
                }
            }
        } else if(method=="POST") local.ContentLength=0;
        using(var response=Response(local)) {
            string text=ReadSmall(response.GetResponseStream());
            Agent("/bridge/reply/"+id,Json.Serialize(new {status=(int)response.StatusCode,body=text}));
        }
    }
    static void Run() {
        using(var instance=new FileStream(Path.Combine(Home,"service.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)) {
            LoadConnection();
            if(!File.Exists(Device)) File.WriteAllText(Device,Guid.NewGuid().ToString("N"));
            Id=File.ReadAllText(Device).Trim();
            string port=Environment.GetEnvironmentVariable("QR_INBOX_TEST_PORT");
            if(port!=null) Port=int.Parse(port);
            File.Delete(Stop);
            string env=Path.Combine(Home,"backend.env");
            // DPAPI holds the saved key. The child receives it only in its own environment.
            File.WriteAllText(env,"TIMEZONE=Europe/Istanbul\n",Encoding.UTF8);
            Process backend=null; bool stopping=false;
            DateTime lastHealthy=DateTime.UtcNow;
            using(var heartbeat=new System.Threading.Timer(delegate {
                if(stopping) return;
                try { Agent("/bridge/ping",null); } catch { }
            },null,Timeout.Infinite,10000)) {
                try {
                    while(!File.Exists(Stop)) {
                        if(backend==null || backend.HasExited) {
                            var info=new ProcessStartInfo(Path.Combine(Path.GetDirectoryName(Exe),"runtime","python.exe"),"-m backend");
                            info.WorkingDirectory=Path.GetDirectoryName(Exe); info.UseShellExecute=false; info.CreateNoWindow=true;
                            info.RedirectStandardOutput=true; info.RedirectStandardError=true;
                            info.EnvironmentVariables["QR_INBOX_CONFIG"]=env;
                            info.EnvironmentVariables["DATA_ROOT"]=Path.Combine(Home,"data");
                            // Redirected Desktops may be on a different drive. Keep atomic
                            // delivery moves on that drive without changing existing databases.
                            string desktop=Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                            if(!string.Equals(Path.GetPathRoot(desktop),Path.GetPathRoot(Home),StringComparison.OrdinalIgnoreCase))
                                info.EnvironmentVariables["DATA_ROOT"]=Path.Combine(desktop,".QRPrintInbox-data");
                            info.EnvironmentVariables["PORT"]=Port.ToString();
                            info.EnvironmentVariables["HOST"]="127.0.0.1";
                            info.EnvironmentVariables["GATEWAY_SECRET"]=Key;
                            info.EnvironmentVariables.Remove("STORAGE_ROOT");
                            string storage=Environment.GetEnvironmentVariable("QR_INBOX_TEST_STORAGE");
                            if(storage!=null) info.EnvironmentVariables["STORAGE_ROOT"]=storage;
                            backend=Process.Start(info); backend.BeginOutputReadLine(); backend.BeginErrorReadLine();
                            lastHealthy=DateTime.UtcNow;
                            Thread.Sleep(1500);
                        }
                        bool backendOk=false;
                        try {
                            var health=Request("http://127.0.0.1:"+Port+"/healthz","GET",false);
                            health.Timeout=3000; health.ReadWriteTimeout=3000;
                            health.Headers["X-Inbox-Gateway"]=Key; health.Headers["X-Inbox-Client-IP"]="127.0.0.1";
                            using(var r=Response(health)) if((int)r.StatusCode!=200) throw new IOException();
                            backendOk=true; lastHealthy=DateTime.UtcNow;
                            heartbeat.Change(0,10000);
                            var message=Json.Deserialize<Dictionary<string,object>>(Agent("/bridge/poll",null));
                            File.WriteAllText(State,"Bağlantı hazır.");
                            if(message["job"]!=null) Job((Dictionary<string,object>)message["job"]);
                        } catch(Exception error) {
                            if(!backendOk && (DateTime.UtcNow-lastHealthy).TotalSeconds>30 &&
                                backend!=null && !backend.HasExited) backend.Kill();
                            string code=error.GetType().Name;
                            var network=error as WebException;
                            if(network!=null) code+=" / "+network.Status;
                            File.WriteAllText(State,"Bağlantı bekleniyor. İnternet ve bağlantı ayarını kontrol edin. ("+code+")");
                            Thread.Sleep(2000);
                        }
                    }
                } finally {
                    stopping=true; heartbeat.Change(Timeout.Infinite,Timeout.Infinite);
                    try { Agent("/bridge/disconnect",null); } catch { }
                    if(backend!=null && !backend.HasExited) {
                        // The embedded interpreter is a real process, not a venv redirector.
                        // This backend does not create child processes.
                        backend.Kill(); backend.WaitForExit(10000);
                    }
                    File.WriteAllText(State,"Durduruldu.");
                }
            }
        }
    }
    internal static void Shortcut(string path,string target,string args) {
        Type type=Type.GetTypeFromProgID("WScript.Shell"); object shell=Activator.CreateInstance(type);
        object link=type.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[]{path});
        Type t=link.GetType();
        t.InvokeMember("TargetPath",BindingFlags.SetProperty,null,link,new object[]{target});
        t.InvokeMember("Arguments",BindingFlags.SetProperty,null,link,new object[]{args});
        t.InvokeMember("WorkingDirectory",BindingFlags.SetProperty,null,link,new object[]{Path.GetDirectoryName(target)});
        t.InvokeMember("Save",BindingFlags.InvokeMethod,null,link,null);
        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link);
        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
    }
    internal static void Extract(string destination) {
        if(IsRunning()) throw new IOException("Güncellemeden önce uygulamayı durdurun.");
        Directory.CreateDirectory(destination);
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using(var archive=new ZipArchive(stream,ZipArchiveMode.Read)) {
            var manifest=new JavaScriptSerializer {MaxJsonLength=2*1024*1024}
                .Deserialize<Dictionary<string,object>>(ReadManifest(archive.GetEntry("manifest.json")));
            var files=(Dictionary<string,object>)manifest["files"];
            foreach(var entry in archive.Entries) {
                if(entry.FullName=="manifest.json") continue;
                if(!files.ContainsKey(entry.FullName) || entry.FullName.Contains("..") || entry.FullName.Contains("\\") || entry.FullName.Contains(":")) throw new IOException();
                string output=Path.GetFullPath(Path.Combine(destination,entry.FullName));
                if(!output.StartsWith(Path.GetFullPath(destination)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new IOException();
                Directory.CreateDirectory(Path.GetDirectoryName(output));
                using(var source=entry.Open()) using(var target=File.Create(output)) source.CopyTo(target);
                using(var sha=SHA256.Create()) using(var check=File.OpenRead(output)) {
                    if(BitConverter.ToString(sha.ComputeHash(check)).Replace("-","").ToLowerInvariant()!=Convert.ToString(files[entry.FullName])) throw new IOException();
                }
            }
        }
        string exe=Path.Combine(destination,"QRPrintInbox.exe");
        if(!string.Equals(Exe,exe,StringComparison.OrdinalIgnoreCase)) File.Copy(Exe,exe,true);
    }
    static string ReadManifest(ZipArchiveEntry entry) {
        using(var reader=new StreamReader(entry.Open())) return reader.ReadToEnd();
    }
    internal static void InstallNow(bool launch=true) {
        Extract(Install);
        string exe=Path.Combine(Install,"QRPrintInbox.exe");
        string menu=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"QR File Inbox.lnk");
        Shortcut(menu,exe,"");
        Shortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup),"QR File Inbox.lnk"),exe,"/background");
        if(launch) Process.Start(exe);
    }
}

class PanelForm : Form {
    Label status; bool setup;
    internal PanelForm(bool installer) {
        setup=installer; Text=setup ? "QR File Inbox — Kurulum":"QR File Inbox";
        ClientSize=new Size(480,330); StartPosition=FormStartPosition.CenterScreen;
        FormBorderStyle=FormBorderStyle.FixedDialog; MaximizeBox=false;
        Font=new Font("Segoe UI",10); BackColor=Color.White;
        var title=new Label {Text=setup ? "QR File Inbox’ı kurun":"Dosyalar doğrudan bu PC’ye gelsin.",Left=24,Top=24,Width=430,Height=40,Font=new Font("Segoe UI",14,FontStyle.Bold)};
        Controls.Add(title);
        status=new Label {Left=24,Top=78,Width=430,Height=65,Text=setup ?
            "Windows 7 SP1 (32/64 bit), 10 ve 11 için.\nYönetici yetkisi veya Python kurulumu gerekmez.":"Bağlantı durumu kontrol ediliyor…"};
        Controls.Add(status);
        if(setup) Add("Kur",160,delegate { InboxApp.InstallNow(); Close(); });
        else {
            Add("Bağlantı dosyasını seç",148,delegate {
                using(var dialog=new OpenFileDialog {Filter="Bağlantı dosyası|*.connection.json"}) {
                    if(dialog.ShowDialog()==DialogResult.OK) { InboxApp.Import(dialog.FileName); status.Text="Bağlantı kaydedildi. Şimdi Başlat’a basın."; }
                }
            });
            Add("Başlat",190,delegate { InboxApp.Start(); status.Text="Başlatılıyor…"; });
            Add("Durdur",232,delegate { File.WriteAllText(InboxApp.Stop,""); status.Text="Durduruluyor…"; });
            var timer=new System.Windows.Forms.Timer {Interval=3000};
            timer.Tick+=delegate { if(File.Exists(InboxApp.State)) { try { status.Text=File.ReadAllText(InboxApp.State); } catch(IOException) { } } };
            timer.Start(); FormClosed+=delegate {timer.Dispose();};
        }
        var note=new Label {Left=24,Top=290,Width=430,Height=30,Text="Dosyalar: Masaüstü / Gelen Dosyalar · Saklama: 14 gün"}; Controls.Add(note);
    }
    void Add(string text,int top,Action action) {
        var button=new Button {Text=text,Left=24,Top=top,Width=430,Height=34};
        button.Click+=delegate {
            button.Enabled=false;
            try { action(); } catch {
                MessageBox.Show(this,"İşlem tamamlanamadı. Bağlantı dosyasını, disk alanını ve uygulamanın durdurulduğunu kontrol edin.","QR File Inbox");
            } finally { if(!IsDisposed) button.Enabled=true; }
        }; Controls.Add(button);
    }
}
