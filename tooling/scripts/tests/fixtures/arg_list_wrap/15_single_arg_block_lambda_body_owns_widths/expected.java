public class Demo
{
    public void run()
    {
        this.performTest(() -> {
            try {
                String defaultResult = engine.findPath(
                    startRecordKey,
                    endRecordKey,
                    maxDegrees,
                    SzRecordKeys.of(avoidances),
                    requiredSources);
            } catch (Exception e) {
            }
        });
    }
}
