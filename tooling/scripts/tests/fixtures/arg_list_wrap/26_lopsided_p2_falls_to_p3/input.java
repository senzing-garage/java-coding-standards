public class Demo
{
    void build(Map<String, Object> config)
    {
        Boolean result = ServiceUtilities.getConfigBoolean(config, "enabled", false);
        this.saveDemoResult("findInterestingByEntityIdDefault", demoResult, true);
    }
}
