public class Demo
{
    void run()
    {
        if (a) {
            if (b) {
                String nativeResult = engine
                    .getNativeApi()
                    .getEntityByRecordId(dataSourceCode, recordID);
            }
        }
    }
}
