public class Demo
{
    void build(Map<String, Object> config)
    {
        this.registerDataSource("CUSTOMERS_AND_EMPLOYEES_AND_VENDORS",
                                configId,
                                true);
        this.saveDemoResult("findInterestingByEntityIdDefault",
                            demoResult,
                            true);
    }
}
