public class Demo
{
    public void run(java.util.Set<String> keys)
    {
        for (Object t : keys) {
            if (t != null) {
                if (keys.isEmpty()) {
                    String defaultResult = engine.findPath(
                        startRecordKey,
                        endRecordKey,
                        maxDegrees,
                        SzRecordKeys.of(avoidances),
                        requiredSources);
                }
            }
        }
    }
}
