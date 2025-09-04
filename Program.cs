using Opc.UaFx; // OpcValue için bu namespace gerekli
using Opc.UaFx.Client;
using System;
using System.Threading.Tasks;

namespace OpcUaClient
{
    class Program
    {
        static void Main(string[] args) // Main metodunu Task döndürmediği için async'ten çıkarıldı.
        {
            // OPC UA Sunucunuzun Endpoint URL'si
            string serverUrl = "opc.tcp://LAPTOP-CNBPLSHA:48010";

            // Okumak ve yazmak istediğiniz Node'un ID'si (NodeId)
            string nodeIdToModify = "ns=3;s=Demo.Dynamic.Scalar.UInt32"; // Bu node'un yazılabilir olduğundan emin olun!

            Console.WriteLine($"OPC UA Sunucusuna bağlanılıyor: {serverUrl}");

            using (var client = new OpcClient(serverUrl))
            {
                try
                {
                    client.Connect();
                    Console.WriteLine("Bağlantı başarılı!");

                    // Mevcut değeri okuma
                    OpcValue currentValue = client.ReadNode(nodeIdToModify);

                    if (currentValue != null && currentValue.Status.IsGood)
                    {
                        Console.WriteLine($"Node ID: {nodeIdToModify}");
                        Console.WriteLine($"Mevcut Değer: {currentValue.Value}");
                        Console.WriteLine($"Zaman Damgası: {currentValue.SourceTimestamp}");
                        Console.WriteLine($"Durum: {currentValue.Status}");
                    }
                    else
                    {
                        Console.WriteLine($"Node '{nodeIdToModify}' okunurken bir sorun oluştu veya değer geçerli değil.");
                        if (currentValue != null)
                        {
                            Console.WriteLine($"Durum: {currentValue.Status}");
                        }
                    }

                    // --------------------------------------------------------------------------------
                    // Yeni değer yazma işlemi
                    // --------------------------------------------------------------------------------

                    // Bu node'un tipi UInt32 olduğu için uint kullanıyoruz.
                    // Yazmak istediğiniz değeri ve node'un veri tipine uygun türü ayarlayın.
                    uint newValue = 12345; // Örnek olarak 12345 değerini yazıyoruz.
                                           // Eğer node Int32 olsaydı int, string olsaydı string kullanırdınız.

                    Console.WriteLine($"\nNode '{nodeIdToModify}' için yeni değer ({newValue}) yazılıyor...");

                    // WriteNode metodunu kullanarak değeri yazın.
                    // Bu metod bir OpcDataValue<T> döndürmez, sadece yazma işleminin başarılı olup olmadığını gösteren bir durum (status) döndürür.
                    OpcStatusCode writeStatus = client.WriteNode(nodeIdToModify, newValue);

                    if (writeStatus.IsGood)
                    {
                        Console.WriteLine($"Değer başarıyla yazıldı. Yeni değer: {newValue}");

                        // Yazdıktan sonra değeri tekrar okuyarak teyit edelim.
                        Console.WriteLine("Yazılan değeri teyit etmek için tekrar okunuyor...");
                        OpcValue confirmedValue = client.ReadNode(nodeIdToModify);

                        if (confirmedValue != null && confirmedValue.Status.IsGood)
                        {
                            Console.WriteLine($"Onaylanmış Değer: {confirmedValue.Value}");
                            Console.WriteLine($"Onaylanmış Durum: {confirmedValue.Status}");
                        }
                        else
                        {
                            Console.WriteLine($"Yazma sonrası node değeri okunurken bir sorun oluştu: {confirmedValue?.Status}");
                        }
                    }
                    else
                    {
                        Console.WriteLine($"Değer yazılırken bir hata oluştu. Durum: {writeStatus}");
                        Console.WriteLine($"Hata Kodu: {writeStatus.GetCode()}");
                        Console.WriteLine($"Hata Açıklaması: {writeStatus.GetDescription()}");
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Bir hata oluştu: {ex.Message}");
                    Console.WriteLine(ex.StackTrace);
                }
                finally
                {
                    if (client.State == OpcClientState.Connected)
                    {
                        client.Disconnect();
                        Console.WriteLine("Bağlantı kesildi.");
                    }
                }
            }

            Console.WriteLine("Uygulama tamamlandı. Çıkmak için bir tuşa basın.");
            Console.ReadKey();
        }
    }
}