public class Demo
{
    public void find(String                  startKey,
                     String                  endKey,
                     int                     degrees,
                     java.util.Set<String>   avoidances,
                     java.util.Set<String>   requiredSources)
    {
        String result = engine.findPath(startKey,
                                        endKey,
                                        degrees,
                                        SzRecordKeys.of(avoidances),
                                        requiredSources);
    }
}
