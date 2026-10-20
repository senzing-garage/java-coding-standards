public class Demo
{
    private Object cachedEntity;

    private long elapsedTimeNanos;

    void run(SzEngine    engine,
             String      dataSource,
             String      recordId,
             long        startTime)
    {
        Object cachedEntity = engine.getNativeApi()
                                    .getEntityByRecordId(dataSource, recordId);
        this.cachedEntity = engine.getNativeApi()
                                  .getEntityByRecordId(dataSource, recordId);
        long elapsedTimeNanos = (System.nanoTime() - startTime)
            / ONE_MILLION_CONST;
        this.elapsedTimeNanos = (System.nanoTime() - startTime)
            / ONE_MILLION_CONST;
    }
}
