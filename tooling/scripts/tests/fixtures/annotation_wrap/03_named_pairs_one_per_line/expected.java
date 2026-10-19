public class Demo
{
    @DisabledIf(
        value = "checkBootstrapBuild",
        disabledReason = "This test only runs against a bootstrap build")
    public void disabled()
    {
    }
}
