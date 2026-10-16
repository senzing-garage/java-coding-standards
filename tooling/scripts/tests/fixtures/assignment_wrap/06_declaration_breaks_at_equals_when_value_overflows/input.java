public class Demo
{
    void run(SzEngine engine, String dataSource, String recordId)
    {
        Object entityForThisRecord = engine.getNativeApi().getEntityByRecordId(dataSource, recordId);
        this.entityForThisRecord = engine.getNativeApi().getEntityByRecordId(dataSource, recordId);
    }
}
