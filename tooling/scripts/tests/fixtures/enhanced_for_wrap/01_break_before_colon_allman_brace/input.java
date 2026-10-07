public class Demo
{
    void run()
    {
        for (Map<String, Map<String, SzFlagMetaData>> parent : parentMaps) {
            for (Map.Entry<String, Map<String, SzFlagMetaData>> entry : parent.entrySet()) {
                doSomething(entry);
            }
        }
    }
}
