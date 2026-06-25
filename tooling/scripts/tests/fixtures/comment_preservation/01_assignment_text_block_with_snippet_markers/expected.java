public class Demo
{
    void run()
    {
        // get a record definition (varies by application)
        String recordDefinition = // @highlight substring="recordDefinition"
                // @highlight type="italic" region="recordDefinition"
                """
                {
                    "DATA_SOURCE": "TEST",
                    "RECORD_ID": "ABC123"
                }
                """;
        // @end region="recordDefinition"
    }
}
