public class Demo
{
    public Object build()
    {
        return Factory.make(alpha)
                      .step1(beta)
                      .step2(gamma)
                      .step3(delta)
                      .finish();
    }
}
