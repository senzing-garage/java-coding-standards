public class Demo
{
    public void run()
    {
        record(source,
               builder(DATA_SOURCE_SUMMARY,
                       ENTITY_COUNT,
                       dataSourceCode,
                       entityId)
                   .build());
    }
}
