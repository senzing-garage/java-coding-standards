public class Demo
{
    void run()
    {
        // @start region="example"
        String recordDefinition = // @highlight region="recordDefinition"
                """
                {
                    "DATA_SOURCE": "TEST"
                }
                """;
        // @end region="recordDefinition"
        System.out.println(recordDefinition);
        // @end region="example"
    }
}
