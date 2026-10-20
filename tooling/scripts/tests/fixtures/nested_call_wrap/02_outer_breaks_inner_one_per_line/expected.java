public class Demo
{
    public void run()
    {
        reportUpdates.add(
            builder(DATA_SOURCE_SUMMARY,
                    ENTITY_COUNT,
                    dataSourceCode,
                    targetSourceCode,
                    entityId)
                .records(-1)
                .build());
    }
}
