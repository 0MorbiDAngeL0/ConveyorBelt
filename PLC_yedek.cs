using System;
using System.Collections.Generic;
using System.Threading;             
using System.Threading.Tasks;
using Opc.Ua;
using Opc.Ua.Client;
using Opc.Ua.Configuration;

namespace OpcUaClientApp
{
    class Program
    {
        static async Task Main(string[] args)
        {
            Console.WriteLine("OPC UA Client Test - UaCPPServer Bağlantısı");
            Console.WriteLine("==============================================");

            string serverUrl = "opc.tcp://LAPTOP-CNBPLSHA:48010";

            try
            {
                var config = CreateApplicationConfiguration();
                var session = await ConnectToServer(config, serverUrl);

                if (session != null && session.Connected)
                {
                    Console.WriteLine($"✅ Server'a başarıyla bağlanıldı: {serverUrl}");
                    Console.WriteLine($"   Session ID: {session.SessionId}\n");

                    await GetServerInfo(session);
                    BrowseRootNodes(session);
                    await TestReadNodes(session);

                    await TestWriteOperations(session);
                    await InteractiveWriteMode(session);

                    Console.WriteLine("\nTEST TAMAMLANDI. Devam etmek için bir tuşa basın...");
                    Console.ReadKey();

                    await session.CloseAsync();
                    session.Dispose();
                    Console.WriteLine("\n✅ Bağlantı kapatıldı");
                }
                else
                {
                    Console.WriteLine("❌ Server'a bağlanılamadı!");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"❌ HATA: {ex.Message}");
                if (ex.InnerException != null)
                    Console.WriteLine($"   Detay: {ex.InnerException.Message}");
            }

            Console.WriteLine("\nÇıkmak için bir tuşa basın...");
            Console.ReadKey();
        }

        static ApplicationConfiguration CreateApplicationConfiguration()
        {
            var config = new ApplicationConfiguration()
            {
                ApplicationName = "OPC UA Test Client",
                ApplicationUri = "urn:localhost:OpcUaTestClient",
                ApplicationType = ApplicationType.Client,

                SecurityConfiguration = new SecurityConfiguration
                {
                    ApplicationCertificate = new CertificateIdentifier(),
                    AutoAcceptUntrustedCertificates = true,
                    RejectSHA1SignedCertificates = false,
                    MinimumCertificateKeySize = 1024,
                },

                TransportConfigurations = new TransportConfigurationCollection(),
                TransportQuotas = new TransportQuotas
                {
                    OperationTimeout = 15000,
                    MaxStringLength = 1048576,
                    MaxByteStringLength = 1048576,
                    MaxArrayLength = 65535,
                    MaxMessageSize = 4194304
                },

                ClientConfiguration = new ClientConfiguration
                {
                    DefaultSessionTimeout = 60000
                },

                TraceConfiguration = new TraceConfiguration()
            };

            config.CertificateValidator = new CertificateValidator();
            config.CertificateValidator.CertificateValidation += (sender, eventArgs) =>
            {
                Console.WriteLine($"🔐 Sertifika kabul ediliyor: {eventArgs.Certificate.Subject}");
                eventArgs.Accept = true;
            };

            return config;
        }

        static async Task<Session> ConnectToServer(ApplicationConfiguration config, string serverUrl)
        {
            Console.WriteLine($"🔄 Server'a bağlanılıyor: {serverUrl}");

            try
            {
                var endpointDescription = CoreClientUtils.SelectEndpoint(serverUrl, false, 15000);
                Console.WriteLine($"   Endpoint seçildi: {endpointDescription.SecurityPolicyUri}");

                var endpointConfiguration = EndpointConfiguration.Create(config);
                var endpoint = new ConfiguredEndpoint(null, endpointDescription, endpointConfiguration);

                var session = await Session.Create(
                    config,
                    endpoint,
                    updateBeforeConnect: false,
                    sessionName: "OPC UA Test Session",
                    sessionTimeout: 60000,
                    identity: null,
                    preferredLocales: null
                );

                return session;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"❌ Bağlantı hatası: {ex.Message}");
                throw;
            }
        }

        static async Task GetServerInfo(Session session)
        {
            Console.WriteLine("📋 Server Bilgileri:");
            try
            {
                var serverStatus = await session.ReadValueAsync(Variables.Server_ServerStatus);
                Console.WriteLine($"   Status: {serverStatus.Value}");

                var serverArray = await session.ReadValueAsync(Variables.Server_ServerArray);
                if (serverArray.Value is string[] servers)
                    Console.WriteLine($"   Server Array: {string.Join(", ", servers)}");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"   ⚠️ Server bilgisi alınamadı: {ex.Message}");
            }
            Console.WriteLine();
        }

        // === Browser helper ile gezme ===
        static void BrowseRootNodes(Session session)
        {
            Console.WriteLine("🔍 Root Node'ları Listeleniyor (Browser helper):");

            try
            {
                var browser = new Browser(session)
                {
                    BrowseDirection = BrowseDirection.Forward,
                    ReferenceTypeId = ReferenceTypeIds.HierarchicalReferences,
                    IncludeSubtypes = true,
                    NodeClassMask = (int)(NodeClass.Object | NodeClass.Variable),
                    ContinueUntilDone = true
                };

                var refs = browser.Browse(Objects.ObjectsFolder);
                foreach (var r in refs)
                    Console.WriteLine($"   📁 {r.DisplayName} ({r.NodeId})");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"   ⚠️ Browse hatası: {ex.Message}");
            }

            Console.WriteLine();
        }

        static async Task TestReadNodes(Session session)
        {
            Console.WriteLine("📖 Test Node'larını Okuyoruz:");

            var standardNodes = new[]
            {
                ("Server State", Variables.Server_ServerStatus_State),
                ("Current Time", Variables.Server_ServerStatus_CurrentTime),
                ("Build Info", Variables.Server_ServerStatus_BuildInfo),
            };

            Console.WriteLine("   📋 Standard Server Node'ları:");
            foreach (var (name, nodeId) in standardNodes)
            {
                try
                {
                    DataValue value;
                    try { value = await session.ReadValueAsync(nodeId); }
                    catch { value = session.ReadValue(nodeId); }

                    if (StatusCode.IsGood(value.StatusCode))
                        Console.WriteLine($"   ✅ {name}: {value.Value}");
                    else
                        Console.WriteLine($"   ❌ {name} - Status: {value.StatusCode}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"   ❌ {name} - Hata: {ex.Message}");
                }
            }

            Console.WriteLine("\n   🔧 UaCPPServer Test Node'ları:");
            var testNodes = new[]
            {
                "ns=3;s=Demo.Static.Scalar.Boolean",
                "ns=3;s=Demo.Dynamic.Scalar.UInt32",
                "ns=3;s=Demo.Dynamic.Scalar.Boolean",
                "ns=3;s=Demo.Static.Scalat.UInt32",
            };

            foreach (var nodeIdString in testNodes)
            {
                try
                {
                    var nodeToRead = NodeId.Parse(nodeIdString);

                    DataValue value;
                    try { value = await session.ReadValueAsync(nodeToRead); }
                    catch { value = session.ReadValue(nodeToRead); }

                    if (StatusCode.IsGood(value.StatusCode))
                        Console.WriteLine($"   ✅ {nodeIdString} = {value.Value} ({value.Value?.GetType().Name})");
                    else
                        Console.WriteLine($"   ❌ {nodeIdString} - Status: {value.StatusCode}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"   ❌ {nodeIdString} - Hata: {ex.Message}");
                }
            }
            Console.WriteLine();
        }

        // ============= YAZMA İŞLEMLERİ =============
        static async Task<bool> WriteNodeValue(Session session, string nodeIdString, object value, string dataType = null)
        {
            try
            {
                var nodeId = NodeId.Parse(nodeIdString);

                object convertedValue = value;
                if (dataType != null)
                {
                    convertedValue = dataType.ToLower() switch
                    {
                        "boolean" or "bool" => Convert.ToBoolean(value),
                        "uint32" => Convert.ToUInt32(value),
                        "int32" => Convert.ToInt32(value),
                        "float" => Convert.ToSingle(value),
                        "double" => Convert.ToDouble(value),
                        "string" => Convert.ToString(value),
                        _ => value
                    };
                }

                var writeValue = new WriteValue()
                {
                    NodeId = nodeId,
                    AttributeId = Attributes.Value,
                    Value = new DataValue(new Variant(convertedValue))
                };

                var requestHeader = new RequestHeader();

                var writeResponse = await session.WriteAsync(
                    requestHeader,
                    new WriteValueCollection { writeValue },
                    CancellationToken.None
                );

                if (writeResponse.Results?.Count > 0)
                {
                    var result = writeResponse.Results[0];
                    if (StatusCode.IsGood(result))
                    {
                        Console.WriteLine($"   ✅ {nodeIdString} = {convertedValue} yazıldı");
                        return true;
                    }
                    else
                    {
                        Console.WriteLine($"   ❌ {nodeIdString} yazma hatası - Status: {result}");
                        return false;
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"   ❌ {nodeIdString} yazma hatası: {ex.Message}");
            }
            return false;
        }

        static async Task TestWriteOperations(Session session)
        {
            Console.WriteLine("✏️ YAZMA İŞLEMLERİ TESTİ");
            Console.WriteLine("========================");

            Console.WriteLine("📖 Yazma öncesi değerler:");
            await ReadSpecificNodes(session);

            Console.WriteLine("\n✏️ Değerleri değiştiriyoruz:");
            var boolNode = "ns=3;s=Demo.Static.Scalar.Boolean";
            await WriteNodeValue(session, boolNode, true, "boolean");

            var uint32Node = "ns=3;s=Demo.Dynamic.Scalar.UInt32";
            await WriteNodeValue(session, uint32Node, 12345u, "uint32");

            var staticUint32Node = "ns=3;s=Demo.Static.Scalar.UInt32";
            await WriteNodeValue(session, uint32Node, 12345u, "uint32");

            var dynamicBoolNode = "ns=3;s=Demo.Dynamic.Scalar.Boolean";
            await WriteNodeValue(session, dynamicBoolNode, false, "boolean");

            Console.WriteLine("\n📖 Yazma sonrası değerler:");
            await ReadSpecificNodes(session);
            Console.WriteLine();
        }

        static async Task ReadSpecificNodes(Session session)
        {
            var nodesToRead = new[]
            {
                "ns=3;s=Demo.Static.Scalar.Boolean",
                "ns=3;s=Demo.Dynamic.Scalar.UInt32",
                "ns=3;s=Demo.Static.Scalar.UInt32",
                "ns=3;s=Demo.Dynamic.Scalar.Boolean"
            };

            foreach (var nodeIdString in nodesToRead)
            {
                try
                {
                    var nodeId = NodeId.Parse(nodeIdString);
                    var value = await session.ReadValueAsync(nodeId);

                    if (StatusCode.IsGood(value.StatusCode))
                        Console.WriteLine($"   📊 {nodeIdString} = {value.Value}");
                    else
                        Console.WriteLine($"   ❌ {nodeIdString} - Status: {value.StatusCode}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"   ❌ {nodeIdString} - Hata: {ex.Message}");
                }
            }
        }

        static async Task InteractiveWriteMode(Session session)
        {
            Console.WriteLine("🎮 İNTERAKTİF YAZMA MODU");
            Console.WriteLine("=======================");
            Console.WriteLine("Değiştirmek istediğiniz değerleri girebilirsiniz (q = çıkış)\n");

            var availableNodes = new Dictionary<string, (string nodeId, string dataType)>
            {
                ["1"] = ("ns=3;s=Demo.Static.Scalar.Boolean", "boolean"),
                ["2"] = ("ns=3;s=Demo.Dynamic.Scalar.UInt32", "uint32"),
                ["3"] = ("ns=3;s=Demo.Dynamic.Scalar.Boolean", "boolean"),
                ["4"] = ("ns=3;s=Demo.Static.Scalar.UInt32", "uint32")
            };

            while (true)
            {
                Console.WriteLine("Mevcut node'lar:");
                Console.WriteLine("1. Static Boolean (ns=3;s=Demo.Static.Scalar.Boolean)");
                Console.WriteLine("2. Dynamic UInt32 (ns=3;s=Demo.Dynamic.Scalar.UInt32)");
                Console.WriteLine("3. Dynamic Boolean (ns=3;s=Demo.Dynamic.Scalar.Boolean)");
                Console.WriteLine("4. Static UInt32 (ns=3;s=Demo.Static.Scalar.UInt32)\n");

                Console.Write("Hangi node'u değiştirmek istiyorsunuz? (1-4, q=çıkış): ");
                var nodeChoice = Console.ReadLine();

                if (nodeChoice?.ToLower() == "q")
                    break;

                if (availableNodes.ContainsKey(nodeChoice))
                {
                    var (nodeId, dataType) = availableNodes[nodeChoice];

                    try
                    {
                        var currentValue = await session.ReadValueAsync(NodeId.Parse(nodeId));
                        Console.WriteLine($"Mevcut değer: {currentValue.Value}");
                    }
                    catch { }

                    Console.Write($"Yeni değer ({dataType}): ");
                    var newValue = Console.ReadLine();

                    if (!string.IsNullOrEmpty(newValue))
                    {
                        await WriteNodeValue(session, nodeId, newValue, dataType);

                        await Task.Delay(100);
                        try
                        {
                            var updatedValue = await session.ReadValueAsync(NodeId.Parse(nodeId));
                            Console.WriteLine($"Güncel değer: {updatedValue.Value}");
                        }
                        catch { }
                    }
                }
                else
                {
                    Console.WriteLine("❌ Geçersiz seçim!");
                }

                Console.WriteLine();
            }
        }
    }
}
