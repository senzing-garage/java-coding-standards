public class Demo
{
    void fitsThenOverflows(SzEngine engine, String dataSource, String recordId)
    {
        Object entity = engine.getNativeApi()
                              .getEntityByRecordId(dataSource, recordId);
        Object entityForThisRecord
            = engine.getNativeApi().getEntityByRecordId(dataSource, recordId);
    }

    void overflowsThenFits(SzEngine engine, String dataSource, String recordId)
    {
        Object entityForThisRecord
            = engine.getNativeApi().getEntityByRecordId(dataSource, recordId);
        Object entity = engine.getNativeApi()
                              .getEntityByRecordId(dataSource, recordId);
    }
}
